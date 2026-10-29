"""Prepare and run frozen QA sequentially, with resumable private result files."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter
import zipfile

from validate_qa_eval import child, digest, read_json, read_jsonl, require, validate
from freeze_qa_baseline import verify

PIPELINE_FILES = ['application/prompts.py', 'application/citations.py', 'application/answer_question.py',
                  'application/retrieve.py', 'adapters/providers/deepseek.py', 'adapters/providers/openai.py']


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    os.replace(temporary, path)


def clean_environment():
    result = {k: v for k, v in os.environ.items() if not k.upper().startswith(('RAG_', 'LITERATURE_'))}
    result.update(ANONYMIZED_TELEMETRY='False', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                  NUMEXPR_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
    return result


def restore_source_bytes(backend, reference, expected_hash, pipeline_files=None):
    """Git normalizes CRLF; restore original bytes only after proving identical source text."""
    target = backend / 'literature_rag'
    pipeline_files=pipeline_files or PIPELINE_FILES
    before = {name: child(target,name).read_bytes() for name in pipeline_files}
    archived_hash = hashlib.sha256(b'\n'.join(before.values())).hexdigest()
    if archived_hash == expected_hash:
        return {'mode': 'archive_bytes_already_match', 'archive_pipeline_sha256': archived_hash}
    require(reference is not None, 'Snapshot fingerprint needs original newline reference source')
    originals = {name: child(Path(reference).resolve(), name).read_bytes() for name in pipeline_files}
    require(hashlib.sha256(b'\n'.join(originals.values())).hexdigest() == expected_hash,
            'Reference source does not match frozen pipeline fingerprint')
    require(all(before[name].replace(b'\r\n', b'\n') == originals[name].replace(b'\r\n', b'\n')
                for name in pipeline_files), 'Reference source differs beyond newline encoding')
    for name, content in originals.items():
        (target / name).write_bytes(content)
    return {'mode': 'original_newlines_restored_no_source_text_change',
            'archive_pipeline_sha256': archived_hash, 'restored_pipeline_sha256': expected_hash,
            'reference_file_hashes': {name: hashlib.sha256(data).hexdigest() for name, data in originals.items()}}


def configuration_probe(backend):
    # Probe imports only configuration code; neither providers nor Chroma are opened.
    source = '''import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,sys.argv[1])
try:
 from literature_rag.config import Settings
 from literature_rag.diagnostics import configuration_snapshot
 p=Path(sys.argv[1])/'.env.literature'
 s=Settings(_env_file=p)
 c=configuration_snapshot(p)
 c['provider_endpoint_fingerprints']={k:hashlib.sha256((getattr(s,k) or '<sdk-default>').encode()).hexdigest() for k in ['llm_base_url','embedding_base_url']}
 c['credentials_present']=bool(s.llm_api_key and s.embedding_api_key)
 print(json.dumps(c))
except Exception:
 print(json.dumps({'preflight_failed':True}))
'''
    process = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', source, str(backend)],
                             env=clean_environment(), capture_output=True, encoding='utf-8', timeout=30)
    require(process.returncode == 0, 'Isolated configuration probe failed')
    probe = json.loads(process.stdout)
    require(not probe.get('preflight_failed') and probe.pop('credentials_present', False), 'Private model configuration unavailable')
    return probe


def source_hashes(backend):
    return {p.relative_to(backend).as_posix(): digest(p) for p in backend.rglob('*.py')}


def prepare(baseline, pack, env_file, run_dir, reference_source=None, suite=None):
    baseline, pack, run_dir = (Path(v).resolve() for v in (baseline, pack, run_dir))
    require(not run_dir.exists(), 'Run directory already exists')
    validation = validate(pack, baseline)
    baseline_validation = verify(baseline)
    frozen, config = read_json(baseline / 'manifest.json'), read_json(baseline / 'configuration.json')
    pack_manifest=read_json(pack/'manifest.json')
    v2=pack_manifest.get('schema_version')==2
    selected_tasks=None
    if v2:
        from qa_eval_v2 import task_selection
        selected_tasks=task_selection(pack,suite or pack_manifest['default_suite'])
        require(bool(selected_tasks),'Selected suite has no executable tasks')
    else:
        require(suite is None,'Suites require a v2 dataset')
    os.umask(0o077)
    run_dir.mkdir(parents=True, mode=0o700)
    (run_dir / 'results').mkdir()
    (run_dir / 'attempts').mkdir()
    with zipfile.ZipFile(baseline / 'code.zip') as archive:
        for entry in archive.infolist():
            if not entry.filename.startswith('backend/'):
                continue
            destination = child(run_dir, entry.filename)
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(entry))
    backend = run_dir / 'backend'
    require((backend / 'literature_worker.py').is_file(), 'Frozen worker missing')
    restoration = restore_source_bytes(backend, reference_source, config['prompt_pipeline_sha256'],config.get('pipeline_source_files'))
    shutil.copytree(baseline / 'library', run_dir / 'library')
    shutil.copytree(pack, run_dir / 'dataset')
    shutil.copyfile(env_file, backend / '.env.literature')
    os.chmod(backend / '.env.literature', 0o600)
    probe = configuration_probe(backend)
    require(all(probe.get(key) == value for key, value in config.items() if key in probe), 'Frozen configuration mismatch')
    require(probe['provider_endpoint_fingerprints'] == config['provider_endpoint_fingerprints'], 'Provider endpoint fingerprint mismatch')
    require(probe['prompt_pipeline_sha256'] == config['prompt_pipeline_sha256'], 'Frozen pipeline fingerprint mismatch')
    metadata = dict(schema_version=1, run_id=run_dir.name, created_at=now(),
                    baseline_id=frozen['baseline_id'], source_commit=frozen['source_commit'],
                    baseline_manifest_sha256=digest(baseline / 'manifest.json'),
                    archive_sha256=digest(baseline / 'code.zip'),
                    dataset_manifest_sha256=digest(pack / 'manifest.json'), configuration=config,
                    configuration_probe=probe, source_byte_restoration=restoration,
                    source_files=source_hashes(backend), initial_library_files={p.relative_to(run_dir / 'library').as_posix(): digest(p)
                    for p in (run_dir / 'library').rglob('*') if p.is_file()},
                    dataset_files={p.relative_to(run_dir / 'dataset').as_posix(): digest(p)
                    for p in (run_dir / 'dataset').rglob('*') if p.is_file()},
                    python=sys.version, packages={d.metadata['Name']: d.version for d in importlib.metadata.distributions()},
                    harness_files={name: digest(Path(__file__).with_name(name)) for name in
                                   ('run_qa_baseline.py', 'validate_qa_eval.py', 'freeze_qa_baseline.py','qa_eval_v2.py','qa_injection_worker.py')},
                    input_policy='Only question and isolated data_dir are sent to frozen worker; no gold labels or answers.',
                    timeout_seconds=config['qa_timeout_seconds'],
                    baseline_validation=baseline_validation, dataset_validation=validation)
    if v2:
        metadata.update(evaluation_schema_version=2,tasks=selected_tasks,selected_suite=suite or pack_manifest['default_suite'])
    # Keep the fixture harness isolated and fingerprinted alongside the frozen source.
    if v2:
        (run_dir/'harness').mkdir()
        for name in ('qa_injection_worker.py',):
            shutil.copyfile(Path(__file__).with_name(name),run_dir/'harness'/name)
    write_json(run_dir / 'run.json', metadata)
    total=len(selected_tasks) if v2 else validation['cases']
    write_json(run_dir / 'progress.json', {'status': 'prepared', 'completed': 0, 'total': total})
    return {'run_id': run_dir.name, 'status': 'prepared', 'tasks': total, 'provider_calls': 0}


def execute_question(worker, library, question, timeout):
    """The payload deliberately excludes references, grading labels and reference answers."""
    return subprocess.run([sys.executable, '-I', '-X', 'utf8', str(worker)],
                          input=json.dumps({'question': question, 'data_dir': str(library)}, ensure_ascii=False),
                          env=clean_environment(), capture_output=True, text=True, encoding='utf-8', timeout=timeout,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def execute_fixture(run_dir, task, question, timeout):
    payload={'backend_dir':str(run_dir/'backend'),'fixture_file':str(child(run_dir/'dataset',task['fixture'])),
             'variant':task['variant'],'question':question}
    return subprocess.run([sys.executable,'-I','-X','utf8',str(run_dir/'harness/qa_injection_worker.py')],
                          input=json.dumps(payload,ensure_ascii=False),env=clean_environment(),
                          capture_output=True,text=True,encoding='utf-8',timeout=timeout,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


def run(run_dir, limit=None, execution_timeout=None):
    from filelock import FileLock
    require(limit is None or type(limit) is int and limit > 0, 'Run limit must be a positive integer')
    require(execution_timeout is None or type(execution_timeout) is int and 5 <= execution_timeout <= 600,
            'Execution timeout must be an integer from 5 to 600 seconds')
    run_dir = Path(run_dir).resolve()
    metadata = read_json(run_dir / 'run.json')
    timeout = execution_timeout if execution_timeout is not None else metadata['timeout_seconds']
    backend = run_dir / 'backend'
    require(source_hashes(backend) == metadata['source_files'], 'Frozen runtime source was changed')
    require(configuration_probe(backend) == metadata['configuration_probe'], 'Private runtime configuration was changed')
    require({p.relative_to(run_dir / 'dataset').as_posix(): digest(p) for p in (run_dir / 'dataset').rglob('*') if p.is_file()}
            == metadata['dataset_files'], 'Run dataset was changed')
    cases = read_jsonl(run_dir / 'dataset/cases.jsonl')
    by_case={c['id']:c for c in cases}
    tasks=metadata.get('tasks') or [{'id':c['id'],'case_id':c['id'],'mode':'retrieval'} for c in cases]
    if metadata.get('evaluation_schema_version')==2:
        for name in ('qa_injection_worker.py',):
            require(digest(run_dir/'harness'/name)==metadata['harness_files'][name],'Fixture harness was changed')
    with FileLock(str(run_dir / '.runner.lock'), timeout=0):
        calls = 0
        for task in tasks:
            case=by_case[task['case_id']]
            result_path = run_dir / 'results' / (task['id'] + '.json')
            attempt_path = run_dir / 'attempts' / (task['id'] + '.json')
            if result_path.exists():
                saved = read_json(result_path)
                require(saved['question'] == case['question'] and saved['case_id'] == case['id']
                        and saved['run_id'] == metadata['run_id'], 'Completed result identity mismatch')
                require(attempt_path.exists() and read_json(attempt_path).get('result_sha256') == digest(result_path),
                        'Completed result checksum mismatch')
                continue
            if limit is not None and calls >= limit:
                break
            require(not attempt_path.exists(), 'Interrupted attempt requires inspection; automatic paid replay refused')
            # Check the code again before each paid operation.
            require(source_hashes(backend) == metadata['source_files'], 'Frozen runtime source was changed')
            started = perf_counter()
            result = dict(run_id=metadata['run_id'], case_id=case['id'], question=case['question'], started_at=now())
            result.update(execution_timeout_seconds=timeout, runner_sha256=digest(Path(__file__)))
            if metadata.get('evaluation_schema_version')==2:
                result.update(task_id=task['id'],suite=task['suite'],capabilities=task['capabilities'],variant=task.get('variant'))
            write_json(attempt_path, {**result, 'status': 'started'})
            calls += 1
            try:
                if task['mode']=='controlled_evidence':
                    process=execute_fixture(run_dir,task,case['question'],timeout)
                else:
                    process = execute_question(backend / 'literature_worker.py', run_dir / 'library',
                                               case['question'], timeout)
                result['worker_stderr_sha256'] = hashlib.sha256(process.stderr.encode()).hexdigest()
                result['worker_stderr_bytes'] = len(process.stderr.encode())
                result['worker_returncode'] = process.returncode
                if process.returncode:
                    result.update(status='failed', reason_code='worker_error', response=None)
                else:
                    try:
                        response = json.loads(process.stdout)
                        require(response.get('status') in {'answered', 'refused', 'failed'}, 'Invalid worker status')
                        require(isinstance(response.get('answer'), str) and isinstance(response.get('citations'), list), 'Invalid worker body')
                        actual = response.get('configuration', {})
                        require(all(actual.get(key) == metadata['configuration_probe'][key] for key in
                                    ('llm_model', 'embedding_model', 'top_k', 'min_score', 'prompt_pipeline_sha256')),
                                'Worker configuration mismatch')
                        result.update(status=response['status'], reason_code=response.get('reason_code'), response=response)
                    except (ValueError, KeyError, TypeError):
                        result.update(status='failed', reason_code='invalid_worker_response', response=None)
            except subprocess.TimeoutExpired:
                result.update(status='failed', reason_code='timeout', response=None)
            result.update(finished_at=now(), end_to_end_ms=round((perf_counter() - started) * 1000))
            write_json(result_path, result)
            write_json(attempt_path, {'case_id': case['id'], 'status': 'completed', 'result_sha256': digest(result_path)})
            results = [read_json(path) for path in sorted((run_dir / 'results').glob('*.json'))]
            progress = {'status': 'completed' if len(results) == len(tasks) else 'running',
                        'completed': len(results), 'total': len(tasks), 'last_case': case['id'],
                        'outcomes': dict(Counter(r['status'] for r in results)), 'updated_at': now()}
            write_json(run_dir / 'progress.json', progress)
            print(json.dumps(progress), flush=True)
    return read_json(run_dir / 'progress.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    preparation = commands.add_parser('prepare')
    for option in ('baseline', 'pack', 'env-file', 'run-dir'):
        preparation.add_argument('--' + option, type=Path, required=True)
    preparation.add_argument('--reference-source', type=Path)
    preparation.add_argument('--suite',choices=['core_text','injection','figure','all_active'])
    execution = commands.add_parser('run')
    execution.add_argument('--run-dir', type=Path, required=True)
    execution.add_argument('--limit', type=int)
    execution.add_argument('--execution-timeout', type=int)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            result = prepare(args.baseline, args.pack, args.env_file, args.run_dir, args.reference_source,args.suite)
        else:
            result = run(args.run_dir, args.limit, args.execution_timeout)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        # Never echo private configuration, provider responses, or raw subprocess stderr.
        message = str(error) if type(error) is ValueError else type(error).__name__
        parser.exit(1, 'QA baseline operation failed: ' + message + '\n')


if __name__ == '__main__':
    main()

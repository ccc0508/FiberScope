"""Replay only the three truncated v3 reviews, once each, at 32768 output tokens."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
import json
import re
import shutil
import subprocess
from time import perf_counter

from filelock import FileLock

import judge_qa_eval as audit
import run_qa_baseline as runner
from validate_qa_eval import require

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.rag-data/evaluations/pfi-evidence-review-20261102-v3'
CONTRACT = ROOT / '.rag-data/evaluations/evidence-review-20261102-v3/contract.json'
OUTPUT = ROOT / '.rag-data/evaluations/evidence-review-32768-retry-20261102'
SELECTED = {'PFI2-024', 'PFI2-031', 'PFI2-032'}


def prepare():
    require(not OUTPUT.exists(), 'Keep earlier paid attempts immutable')
    original = audit.read_json(SOURCE / 'run.json')
    contract = audit.read_json(CONTRACT)
    require(audit.digest(SOURCE / 'run.json') == contract['run_sha256'], 'Original run changed')
    require(runner.source_hashes(SOURCE / 'backend') == original['source_files'], 'Original code changed')
    require(runner.configuration_probe(SOURCE / 'backend') == original['configuration_probe'], 'Original settings changed')
    failed = []
    originals = {}
    for task in original['tasks']:
        path = SOURCE / 'results' / (task['id'] + '.json')
        row = audit.read_json(path)
        require(audit.read_json(SOURCE / 'attempts' / path.name)['result_sha256'] == audit.digest(path), 'Original result changed')
        originals[task['id']] = audit.digest(path)
        if row['response']['evidence_review']['status'] == 'failed':
            require(row['response']['evidence_review']['reason_code'] == 'review_output_truncated', 'Unexpected failure')
            failed.append(task)
    require({t['id'] for t in failed} == SELECTED, 'Failed subset changed; do not add other questions')
    require(audit.digest(SOURCE / 'backend/evidence-review-cache.json') == original['evidence_review_control']['cache_sha256'], 'Draft cache changed')
    require(audit.digest(SOURCE / 'backend/evidence_review_eval_worker.py') == original['evidence_review_control']['worker_sha256'], 'Worker changed')
    OUTPUT.mkdir(parents=True)
    shutil.copytree(SOURCE / 'backend', OUTPUT / 'backend', ignore=shutil.ignore_patterns('__pycache__'))
    env = OUTPUT / 'backend/.env.literature'
    before = env.read_bytes()
    pattern = rb'(?m)^(RAG_EVIDENCE_REVIEW_MAX_OUTPUT_TOKENS=)(["\x27]?)16384\2(\r?)$'
    changed, count = re.subn(pattern, lambda m: m[1] + m[2] + b'32768' + m[2] + m[3], before)
    require(count == 1, 'Unexpected frozen output budget')
    env.write_bytes(changed)
    expected = deepcopy(original['configuration_probe'])
    expected['evidence_review']['max_output_tokens'] = 32768
    require(runner.configuration_probe(OUTPUT / 'backend') == expected, 'Settings changed beyond the output cap')
    meta = dict(run_id=OUTPUT.name, created_at=audit.now(), tasks=failed,
                source_run_sha256=audit.digest(SOURCE / 'run.json'), source_results=originals,
                source_files=original['source_files'], configuration_probe=expected,
                evidence_review_control=original['evidence_review_control'],
                private_env_sha256=audit.digest(env), controller_sha256=audit.digest(Path(__file__)),
                changed_parameter={'max_output_tokens': {'before': 16384, 'after': 32768}},
                max_paid_review_calls=3, automatic_retries=0, new_generation_calls=0,
                new_retrieval_calls=0, new_judge_calls=0,
                policy='One new independent review per previously truncated answer; preserve every old result.')
    audit.write(OUTPUT / 'run.json', meta)
    (OUTPUT / 'attempts').mkdir()
    (OUTPUT / 'results').mkdir()
    return {'prepared': [t['id'] for t in failed], 'max_paid_review_calls': 3}


def verify():
    meta = audit.read_json(OUTPUT / 'run.json')
    require(audit.digest(Path(__file__)) == meta['controller_sha256'], 'Controller changed')
    require(audit.digest(SOURCE / 'run.json') == meta['source_run_sha256'], 'Original run changed')
    require({t['id'] for t in meta['tasks']} == SELECTED, 'Subset changed')
    require(all(audit.digest(SOURCE / 'results' / (tid + '.json')) == h for tid, h in meta['source_results'].items()), 'Original results changed')
    require(runner.source_hashes(OUTPUT / 'backend') == meta['source_files'], 'Frozen code changed')
    require(audit.digest(OUTPUT / 'backend/.env.literature') == meta['private_env_sha256'], 'Private settings changed')
    require(runner.configuration_probe(OUTPUT / 'backend') == meta['configuration_probe'], 'Effective settings changed')
    control = meta['evidence_review_control']
    require(audit.digest(OUTPUT / 'backend/evidence-review-cache.json') == control['cache_sha256'], 'Review cache changed')
    require(audit.digest(OUTPUT / 'backend/evidence_review_eval_worker.py') == control['worker_sha256'], 'Worker changed')
    return meta


def run():
    meta = verify()

    def one(task):
        tid = task['id']
        result_path = OUTPUT / 'results' / (tid + '.json')
        attempt_path = OUTPUT / 'attempts' / (tid + '.json')
        require(not result_path.exists() and not attempt_path.exists(), 'Do not replay an existing paid attempt')
        old = audit.read_json(SOURCE / 'results' / result_path.name)
        audit.write(attempt_path, {'status': 'started', 'case_id': tid, 'started_at': audit.now()})
        started = perf_counter()
        row = dict(case_id=tid, question=old['question'], prior_result_sha256=audit.digest(SOURCE / 'results' / result_path.name))
        try:
            process = runner.execute_question(OUTPUT / 'backend/evidence_review_eval_worker.py', SOURCE / 'library', old['question'], 240)
            row.update(worker_returncode=process.returncode, stderr_sha256=audit.sha(process.stderr))
            require(process.returncode == 0, 'Worker failed; inspect this paid attempt instead of retrying')
            response = json.loads(process.stdout)
            row['response'] = response
            trace, prior = response['evidence_review'], old['response']['evidence_review']
            for key in ['question_sha256', 'draft_sha256', 'evidence_sha256']:
                require(trace[key] == prior[key], 'Model input changed: ' + key)
            require(response['retrieved_evidence'] == old['response']['retrieved_evidence'], 'Source text changed')
            require(not response['generation_calls'] and not response['query_rewrite_calls'] and not response['rerank_calls'], 'Unexpected extra model calls')
            if trace.get('model_info'):
                require(trace['model_info']['request_sha256'] == prior['model_info']['request_sha256'], 'Actual model messages or source image bytes changed')
            require(response['configuration']['evidence_review']['max_output_tokens'] == 32768, 'Wrong output cap')
            row['input_equivalence_verified'] = True
        except subprocess.TimeoutExpired:
            row.update(response=None, error='worker_timeout')
        finally:
            row.update(finished_at=audit.now(), end_to_end_ms=round((perf_counter() - started) * 1000))
            audit.write(result_path, row)
            audit.write(attempt_path, {'status': 'completed', 'result_sha256': audit.digest(result_path)})
        trace = (row.get('response') or {}).get('evidence_review', {})
        return dict(case_id=tid, status=trace.get('status'), reason_code=trace.get('reason_code'),
                    usage=trace.get('usage'), latency_ms=trace.get('latency_ms'))

    with FileLock(str(OUTPUT / '.runner.lock'), timeout=0):
        todo = []
        for task in meta['tasks']:
            path = OUTPUT / 'results' / (task['id'] + '.json')
            attempt = OUTPUT / 'attempts' / path.name
            if path.exists():
                require(audit.read_json(attempt)['result_sha256'] == audit.digest(path), 'Completed attempt changed')
            else:
                require(not attempt.exists(), 'Interrupted paid attempt needs inspection')
                todo.append(task)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for f in as_completed([pool.submit(one, t) for t in todo]):
                print(audit.encode(f.result()), flush=True)
    verify()
    return {'completed': len(list((OUTPUT / 'results').glob('*.json'))), 'planned': 3, 'new_judge_calls': 0}


if __name__ == '__main__':
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'verify'])
    args = parser.parse_args()
    result = {'prepare': prepare, 'run': run, 'verify': lambda: {'verified': bool(verify())}}[args.action]()
    print(audit.encode(result), flush=True)

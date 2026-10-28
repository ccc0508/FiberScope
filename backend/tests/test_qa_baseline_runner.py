"""No provider calls: frozen source, private output, timeouts and no automatic replay."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
saved_path = sys.path[:]
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('run_qa_baseline', SCRIPTS / 'run_qa_baseline.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
finally:
    sys.path[:] = saved_path


def test_worker_payload_contains_no_gold_answers(monkeypatch, tmp_path):
    captured = {}
    def fake_run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, '{}', '')
    monkeypatch.setattr(runner.subprocess, 'run', fake_run)
    runner.execute_question(tmp_path / 'worker.py', tmp_path / 'library', 'user question', 90)
    assert json.loads(captured['input']) == {'question': 'user question', 'data_dir': str(tmp_path / 'library')}
    assert captured['timeout'] == 90
    assert '-I' in captured['command']


def test_environment_cannot_override_frozen_settings(monkeypatch):
    monkeypatch.setenv('RAG_TOP_K', '1')
    monkeypatch.setenv('LITERATURE_TIMEOUT_SECONDS', '5')
    environment = runner.clean_environment()
    assert 'RAG_TOP_K' not in environment
    assert 'LITERATURE_TIMEOUT_SECONDS' not in environment
    assert environment['OPENBLAS_NUM_THREADS'] == '1'


@pytest.fixture
def source_pair(tmp_path):
    backend = tmp_path / 'backend'
    reference = tmp_path / 'reference'
    for i, name in enumerate(runner.PIPELINE_FILES):
        target, original = backend / 'literature_rag' / name, reference / name
        target.parent.mkdir(parents=True, exist_ok=True)
        original.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'x = 1\ny = 2\n')
        original.write_bytes(b'x = 1\r\ny = 2\n' if i % 2 else b'x = 1\r\ny = 2\r\n')
    fingerprint = hashlib.sha256(b'\n'.join((reference / name).read_bytes() for name in runner.PIPELINE_FILES)).hexdigest()
    return backend, reference, fingerprint


def test_restores_mixed_newlines_only_when_source_text_identical(source_pair):
    backend, reference, fingerprint = source_pair
    result = runner.restore_source_bytes(backend, reference, fingerprint)
    assert result['restored_pipeline_sha256'] == fingerprint
    assert all((backend / 'literature_rag' / n).read_bytes() == (reference / n).read_bytes() for n in runner.PIPELINE_FILES)


def test_rejects_semantic_change_even_with_newline_reference(source_pair):
    backend, reference, _ = source_pair
    (reference / runner.PIPELINE_FILES[0]).write_bytes(b'x = 999\n')
    fingerprint = hashlib.sha256(b'\n'.join((reference / name).read_bytes() for name in runner.PIPELINE_FILES)).hexdigest()
    with pytest.raises(ValueError, match='beyond newline'):
        runner.restore_source_bytes(backend, reference, fingerprint)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    for folder in ['backend', 'library', 'dataset', 'results', 'attempts']:
        (tmp_path / folder).mkdir()
    (tmp_path / 'backend/literature_worker.py').write_text('# frozen fixture', encoding='utf-8')
    (tmp_path / 'dataset/cases.jsonl').write_text(json.dumps({'id': 'PFI-001', 'question': 'test question'}) + '\n', encoding='utf-8')
    probe = {'llm_model': 'fixture', 'embedding_model': 'embed', 'top_k': 8,
             'min_score': .35, 'prompt_pipeline_sha256': 'fixture-fingerprint'}
    metadata = {'run_id': 'fixture', 'source_files': runner.source_hashes(tmp_path / 'backend'),
                'configuration_probe': probe, 'timeout_seconds': 90,
                'dataset_files': {'cases.jsonl': runner.digest(tmp_path / 'dataset/cases.jsonl')}}
    runner.write_json(tmp_path / 'run.json', metadata)
    runner.write_json(tmp_path / 'progress.json', {'status': 'prepared', 'completed': 0})
    monkeypatch.setattr(runner, 'configuration_probe', lambda backend: dict(probe))
    return tmp_path


def response(prepared, status='answered'):
    probe = runner.read_json(prepared / 'run.json')['configuration_probe']
    return subprocess.CompletedProcess([], 0, json.dumps({'status': status, 'answer': 'test answer',
                                                         'citations': [], 'configuration': probe}), '')


def test_completed_question_is_never_replayed(prepared, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, 'execute_question', lambda *a: calls.append(a) or response(prepared))
    assert runner.run(prepared)['completed'] == 1
    assert runner.run(prepared)['completed'] == 1
    assert len(calls) == 1


def test_invalid_run_limit_prevents_provider_call(prepared, monkeypatch):
    monkeypatch.setattr(runner, 'execute_question', lambda *a: pytest.fail('must not call provider'))
    with pytest.raises(ValueError, match='positive integer'):runner.run(prepared, limit=0)


def test_limited_pilot_can_resume_without_replaying_result(prepared, monkeypatch):
    metadata=runner.read_json(prepared/'run.json')
    metadata['tasks']=[{'id':'PFI-001','case_id':'PFI-001','mode':'retrieval'},
                       {'id':'PFI-002','case_id':'PFI-002','mode':'retrieval'}]
    path=prepared/'dataset/cases.jsonl'
    path.write_text('\n'.join(json.dumps({'id':f'PFI-{i:03}','question':f'question {i}'}) for i in (1,2))+'\n',encoding='utf-8')
    metadata['dataset_files']['cases.jsonl']=runner.digest(path);runner.write_json(prepared/'run.json',metadata)
    calls=[]
    monkeypatch.setattr(runner,'execute_question',lambda *a:calls.append(a) or response(prepared))
    assert runner.run(prepared,limit=1)['completed']==1 and len(calls)==1
    assert runner.run(prepared,limit=1)['completed']==2 and len(calls)==2
    assert runner.run(prepared,limit=1)['completed']==2 and len(calls)==2


def test_unknown_interrupted_attempt_requires_inspection(prepared, monkeypatch):
    runner.write_json(prepared / 'attempts/PFI-001.json', {'status': 'started'})
    monkeypatch.setattr(runner, 'execute_question', lambda *a: pytest.fail('must not replay'))
    with pytest.raises(ValueError, match='Interrupted attempt'):
        runner.run(prepared)


def test_modified_completed_result_is_not_silently_reused(prepared, monkeypatch):
    monkeypatch.setattr(runner, 'execute_question', lambda *a: response(prepared))
    runner.run(prepared)
    path = prepared / 'results/PFI-001.json'
    result = runner.read_json(path)
    result['response']['answer'] = 'modified after run'
    runner.write_json(path, result)
    with pytest.raises(ValueError, match='result checksum'):
        runner.run(prepared)


def test_timeout_is_a_failure_not_a_semantic_refusal(prepared, monkeypatch):
    def timeout(*args):
        raise subprocess.TimeoutExpired('fixture', 90)
    monkeypatch.setattr(runner, 'execute_question', timeout)
    runner.run(prepared)
    saved = runner.read_json(prepared / 'results/PFI-001.json')
    assert saved['status'] == 'failed'
    assert saved['reason_code'] == 'timeout'
    assert saved['response'] is None


def test_raw_worker_errors_are_not_saved(prepared, monkeypatch):
    monkeypatch.setattr(runner, 'execute_question', lambda *a: subprocess.CompletedProcess([], 1, 'secret stdout', 'secret stderr'))
    runner.run(prepared)
    saved = (prepared / 'results/PFI-001.json').read_text(encoding='utf-8')
    assert 'secret stdout' not in saved and 'secret stderr' not in saved
    assert json.loads(saved)['reason_code'] == 'worker_error'


def test_modified_runtime_source_prevents_paid_call(prepared, monkeypatch):
    (prepared / 'backend/literature_worker.py').write_text('# changed fixture', encoding='utf-8')
    monkeypatch.setattr(runner, 'execute_question', lambda *a: pytest.fail('must not call provider'))
    with pytest.raises(ValueError, match='runtime source'):
        runner.run(prepared)


def test_modified_dataset_prevents_paid_call(prepared, monkeypatch):
    (prepared / 'dataset/cases.jsonl').write_text('{}\n', encoding='utf-8')
    monkeypatch.setattr(runner, 'execute_question', lambda *a: pytest.fail('must not call provider'))
    with pytest.raises(ValueError, match='dataset was changed'):
        runner.run(prepared)

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app import literature
from app.qa_history import HistoryStore
from tests.test_literature_api import configured, client_for, finished, close_clients
from literature_rag.diagnostics import configuration_snapshot, provider_usage

BASE = '/api/v1/literature'
RESULT = {'status': 'answered', 'answer': '纤维结构发生变化 [1]', 'latency_ms': 1,
          'citations': [{'ref': '[1]', 'chunk_id': 'chunk1', 'document_id': 'doc1', 'filename': 'paper.pdf', 'page_start': 3, 'page_end': 3, 'excerpt': 'original evidence'}],
          'retrieved_evidence': [{'ref': '[1]', 'chunk_id': 'chunk1', 'text': 'original evidence', 'score': .9},
                                 {'ref': '[2]', 'chunk_id': 'chunk2', 'text': 'unused original evidence', 'score': .7}],
          'claims': [{'text': '纤维结构发生变化', 'citation_refs': ['[1]']}],
          'generation_calls': [{'attempt': 1, 'usage': {'total_tokens': 100}}]}


def test_private_history_feedback_export_and_cookie(configured, monkeypatch):
    monkeypatch.setattr(literature, 'run_answer', lambda *a: json.loads(json.dumps(RESULT)))
    owner = client_for(configured)
    response = owner.get(BASE + '/history')
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/api/v1/literature' in cookie
    response = owner.post(BASE + '/ask', json={'question': '打浆影响？'})
    record = finished(owner, response.json()['id'])
    record_id = record['id']
    assert record['result']['retrieved_evidence'] == RESULT['retrieved_evidence']
    assert 'owner_id' not in record and 'request_key' not in record
    app = owner.app
    with TestClient(app) as stranger:
        assert stranger.get(BASE + '/history').json()['pagination']['total'] == 0
        assert stranger.get(BASE + '/history/' + record_id).status_code == 404
        assert stranger.post(BASE + '/history/' + record_id + '/feedback', json={'rating': 'helpful'}).status_code == 404
        assert stranger.get(BASE + '/history/export').content == b''
        stranger.cookies.set('fiber_qa_session', 'invented-token', path='/api/v1/literature')
        assert stranger.get(BASE + '/history/' + record_id).status_code == 404
    # Original owner continues to work after another browser disconnects.
    feedback = {'rating': 'inaccurate', 'tags': ['unsupported_citation'], 'note': '原文不支持该结论'}
    assert owner.post(BASE + '/history/' + record_id + '/feedback', json=feedback).status_code == 200
    assert owner.get(BASE + '/history/' + record_id).json()['feedback']['note'] == feedback['note']
    assert owner.post(BASE + '/history/' + record_id + '/feedback', json={'rating': 'helpful', 'tags': [], 'note': '已核对'}).status_code == 200
    response = owner.get(BASE + '/history/export')
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-type'].startswith('application/x-ndjson')
    exported = [json.loads(line) for line in response.text.splitlines()]
    assert exported[0]['feedback']['rating'] == 'helpful'
    assert len(exported[0]['result']['retrieved_evidence']) == 2
    assert 'owner_id' not in response.text and owner.cookies.get('fiber_qa_session') not in response.text
    # Source metadata changes cannot rewrite the saved evidence snapshot.
    with sqlite3.connect(configured.root / 'metadata.sqlite3') as conn:
        conn.execute("UPDATE documents SET filename='new.pdf'")
    assert owner.get(BASE + '/history/' + record_id).json()['result']['citations'][0]['filename'] == 'paper.pdf'


def test_idempotency_in_progress_after_completion_and_origin(configured, monkeypatch):
    entered, release = Event(), Event()
    calls = []
    def blocked(*args):
        calls.append(args)
        entered.set()
        assert release.wait(5)
        return dict(RESULT)
    monkeypatch.setattr(literature, 'run_answer', blocked)
    client = client_for(configured)
    client.get(BASE + '/history')
    payload = {'question': '打浆影响？', 'request_id': str(uuid4())}
    response = client.post(BASE + '/ask', json=payload)
    assert response.status_code == 202 and entered.wait(5)
    record_id = response.json()['id']
    try:
        duplicate = client.post(BASE + '/ask', json=payload)
        assert duplicate.status_code == 202 and duplicate.json()['id'] == record_id
        assert client.post(BASE + '/ask', json={**payload, 'question': '不同问题'}).status_code == 409
        assert client.post(BASE + '/ask', json={'question': '另一个问题'}).status_code == 429
        assert client.post(BASE + '/history/' + record_id + '/feedback', json={'rating': 'helpful'}).status_code == 409
        for path, body in [(BASE + '/ask', payload), (BASE + '/history/' + record_id + '/feedback', {'rating': 'helpful'})]:
            assert client.post(path, json=body, headers={'Origin': 'https://evil.example'}).status_code == 403
    finally:
        release.set()
    finished(client, record_id)
    replay = client.post(BASE + '/ask', json=payload)
    assert replay.status_code == 200 and replay.json()['id'] == record_id
    assert len(calls) == 1


def test_browser_origin_behind_proxy_and_https_cookie(configured, monkeypatch):
    monkeypatch.setattr(literature, 'run_answer', lambda *a: dict(RESULT))
    client = client_for(configured)
    headers = {'Origin': 'https://share.example', 'X-Forwarded-Host': 'share.example', 'X-Forwarded-Proto': 'https', 'Sec-Fetch-Site': 'same-origin'}
    response = client.post(BASE + '/ask', json={'question': '代理来源校验？'}, headers=headers)
    assert response.status_code == 202
    assert 'Secure' in response.headers['set-cookie']
    # The browser will send a Secure cookie only over HTTPS.
    secure_client = TestClient(client.app, base_url='https://testserver')
    secure_client.cookies.update(client.cookies)
    finished(secure_client, response.json()['id'])
    bad = client.post(BASE + '/ask', json={'question': '代理来源校验？'}, headers={**headers, 'Origin': 'https://evil.example'})
    assert bad.status_code == 403


def test_job_survives_request_and_can_be_restored_with_same_cookie(configured, monkeypatch):
    entered, release = Event(), Event()
    def blocked(*a):
        entered.set()
        assert release.wait(5)
        return dict(RESULT)
    monkeypatch.setattr(literature, 'run_answer', blocked)
    client = client_for(configured)
    client.get(BASE + '/history')
    response = client.post(BASE + '/ask', json={'question': '后台继续处理？'})
    assert entered.wait(5)
    record_id = response.json()['id']
    # The request has returned while generation is still blocked.
    assert client.get(BASE + '/history/' + record_id).json()['status'] == 'processing'
    release.set()
    record = finished(client, record_id)
    saved_cookie = client.cookies.get('fiber_qa_session')
    # A reload/recreated client needs only the existing session cookie.
    refreshed = TestClient(client.app)
    refreshed.cookies.set('fiber_qa_session', saved_cookie, path='/api/v1/literature')
    assert refreshed.get(BASE + '/history/' + record_id).json()['result'] == record['result']


@pytest.mark.parametrize('failure,reason,status', [(504, 'timeout', 504), (503, 'worker_error', 503)])
def test_failed_jobs_are_saved_without_raw_errors(configured, monkeypatch, failure, reason, status):
    def fail(*a):
        raise literature.HTTPException(failure, 'secret-key-and-provider-text')
    monkeypatch.setattr(literature, 'run_answer', fail)
    client = client_for(configured)
    record = finished(client, client.post(BASE + '/ask', json={'question': '失败如何处理？'}).json()['id'])
    assert record['status'] == 'failed' and record['reason_code'] == reason and record['error_status'] == status
    assert record['latency_ms'] is not None and 'secret-key' not in json.dumps(record)


def test_save_failure_is_explicit_and_not_visible_to_strangers(configured, monkeypatch):
    monkeypatch.setattr(literature, 'run_answer', lambda *a: dict(RESULT))
    attempted = Event()
    def fail_save(*a):
        attempted.set()
        raise sqlite3.OperationalError('secret internal disk path')
    monkeypatch.setattr(HistoryStore, 'complete', fail_save)
    client = client_for(configured)
    response = client.post(BASE + '/ask', json={'question': '保存失败？'})
    record_id = response.json()['id']
    assert attempted.wait(5)
    # Wait for the worker to publish its save-error flag.
    import time
    for _ in range(50):
        response = client.get(BASE + '/history/' + record_id)
        if response.status_code == 503:
            break
        time.sleep(.01)
    assert response.status_code == 503 and 'secret' not in response.text
    stranger = TestClient(client.app)
    assert stranger.get(BASE + '/history/' + record_id).status_code == 404


def test_recovery_pagination_literal_search_and_feedback_validation(configured):
    store = HistoryStore(configured.root / 'qa_history.sqlite3')
    store.initialize()
    owner, token = store.session(None)
    pending = store.create(owner, str(uuid4()), '原文 100% 的问题', {'llm_model': 'fixture'})
    for i in range(6):
        record = store.create(owner, str(uuid4()), f'历史问题 {i}', {})
        store.complete(record['id'], dict(RESULT), 20)
    client = client_for(configured)
    client.cookies.set('fiber_qa_session', token, path='/api/v1/literature')
    assert client.get(BASE + '/history/' + pending['id']).json()['status'] == 'interrupted'
    assert client.get(BASE + '/history', params={'q': '%'}).json()['pagination']['total'] == 1
    assert client.get(BASE + '/history', params={'q': "'; DROP TABLE questions;--"}).json()['data'] == []
    page1 = client.get(BASE + '/history', params={'page_size': 3}).json()
    page2 = client.get(BASE + '/history', params={'page_size': 3, 'page': 2}).json()
    assert page1['pagination']['total'] == 7 and page1['pagination']['total_pages'] == 3
    assert set(x['id'] for x in page1['data']).isdisjoint(x['id'] for x in page2['data'])
    for payload in [{'rating': 'wrong'}, {'rating': 'helpful', 'tags': ['numeric_error']},
                    {'rating': 'inaccurate', 'tags': ['numeric_error', 'numeric_error']},
                    {'rating': 'inaccurate', 'tags': ['unknown']}, {'rating': 'helpful', 'note': 'x' * 2001}]:
        assert client.post(BASE + '/history/' + record['id'] + '/feedback', json=payload).status_code == 422


def test_single_process_lock_prevents_false_recovery(configured, monkeypatch):
    entered, release = Event(), Event()
    def blocked(*a):
        entered.set()
        assert release.wait(5)
        return dict(RESULT)
    monkeypatch.setattr(literature, 'run_answer', blocked)
    first = client_for(configured)
    record_id = first.post(BASE + '/ask', json={'question': '锁测试问题'}).json()['id']
    assert entered.wait(5)
    try:
        second = client_for(configured)
        assert second.get(BASE + '/history').status_code == 503
        assert first.get(BASE + '/history/' + record_id).json()['status'] == 'processing'
    finally:
        release.set()
    finished(first, record_id)


def test_configuration_and_usage_are_allowlisted_and_backup_restores(configured, tmp_path):
    env = tmp_path / 'settings.env'
    env.write_text('RAG_LLM_MODEL=fixture\nRAG_LLM_API_KEY=secret-key\nRAG_EMBEDDING_API_KEY=another-secret\nRAG_LLM_BASE_URL=https://private.example\n', encoding='utf-8')
    config = configuration_snapshot(env)
    assert config['llm_model'] == 'fixture'
    assert len(config['prompt_pipeline_sha256']) == 64
    assert 'secret' not in json.dumps(config) and 'private.example' not in json.dumps(config)
    assert provider_usage(SimpleNamespace(usage=SimpleNamespace(total_tokens=12, completion_tokens=4, private='secret'))) == {'completion_tokens': 4, 'total_tokens': 12}
    assert provider_usage(SimpleNamespace()) is None
    store = HistoryStore(configured.root / 'qa_history.sqlite3')
    store.initialize()
    owner, token = store.session(None)
    record = store.create(owner, str(uuid4()), '备份测试问题', config)
    store.complete(record['id'], dict(RESULT), 30)
    store.feedback(owner, record['id'], 'helpful', [], '已核对')
    root = Path(__file__).resolve().parents[2]
    backup = tmp_path / 'backup.sqlite3'
    exported = tmp_path / 'export.jsonl'
    for action, destination in [('backup', backup), ('export', exported)]:
        command = [sys.executable, str(root / 'scripts/manage_qa_history.py'), action, '--database', str(store.path), '--output', str(destination)]
        subprocess.run(command, check=True, capture_output=True)
        assert subprocess.run(command, capture_output=True).returncode != 0
    restored = HistoryStore(backup).get(owner, record['id'])
    assert restored['result']['retrieved_evidence'] == RESULT['retrieved_evidence']
    assert restored['feedback']['note'] == '已核对'
    lines = [json.loads(line) for line in exported.read_text(encoding='utf-8').splitlines()]
    assert len(lines) == 1 and lines[0]['schema_version'] == 1
    assert 'owner_id' not in exported.read_text(encoding='utf-8') and token not in exported.read_text(encoding='utf-8')

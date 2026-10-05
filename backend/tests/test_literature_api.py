import json
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import literature

_clients = []


@pytest.fixture(autouse=True)
def close_clients():
    yield
    while _clients:
        _clients.pop().__exit__(None, None, None)


def finished(client, record_id):
    for _ in range(100):
        response = client.get(f'/api/v1/literature/history/{record_id}')
        assert response.status_code == 200
        body = response.json()
        if body['status'] != 'processing':
            return body
        time.sleep(.02)
    pytest.fail('worker did not finish')


@pytest.fixture
def configured(tmp_path):
    (tmp_path / 'papers').mkdir()
    (tmp_path / 'papers/paper.pdf').write_bytes(b'%PDF-1.4\nfixture')
    with sqlite3.connect(tmp_path / 'metadata.sqlite3') as conn:
        conn.execute('CREATE TABLE documents (id TEXT, filename TEXT, file_path TEXT, status TEXT, page_count INTEGER, chunk_count INTEGER)')
        conn.execute("INSERT INTO documents VALUES ('doc1','paper.pdf','papers/paper.pdf','completed',14,44)")
    return literature.LiteratureSettings(_env_file=None, enabled=True, data_dir=tmp_path)


def client_for(config):
    app = FastAPI()
    app.include_router(literature.router(config))
    client = TestClient(app)
    client.__enter__()
    _clients.append(client)
    return client


def test_documents_and_pdf_do_not_expose_local_paths(configured):
    client = client_for(configured)
    response = client.get('/api/v1/literature/documents')
    assert response.status_code == 200
    assert response.json()['documents'] == [{'id':'doc1','filename':'paper.pdf','page_count':14,'chunk_count':44}]
    response = client.get('/api/v1/literature/documents/doc1/pdf')
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['content-disposition'].startswith('inline')
    assert response.content.startswith(b'%PDF')
    assert client.get('/api/v1/literature/documents/unknown/pdf').status_code == 404
    with sqlite3.connect(configured.root / 'metadata.sqlite3') as conn:
        conn.execute("UPDATE documents SET file_path='../outside.pdf'")
    assert client.get('/api/v1/literature/documents/doc1/pdf').status_code == 404


@pytest.mark.parametrize('payload', [{}, {'question':' '}, {'question':'x'}, {'question':'x'*2001}, {'question':'有效问题','path':'../../secret'}])
def test_question_validation(configured, monkeypatch, payload):
    monkeypatch.setattr(literature, 'run_answer', lambda *a: pytest.fail('invalid input reached provider'))
    assert client_for(configured).post('/api/v1/literature/ask', json=payload).status_code == 422


def test_disabled_and_empty_library_do_not_call_model(configured, monkeypatch):
    monkeypatch.setattr(literature, 'run_answer', lambda *a: pytest.fail('unexpected provider call'))
    disabled = configured.model_copy(update={'enabled':False})
    assert client_for(disabled).get('/api/v1/literature/documents').json()['enabled'] is False
    assert client_for(disabled).post('/api/v1/literature/ask', json={'question':'打浆影响？'}).status_code == 503
    with sqlite3.connect(configured.root / 'metadata.sqlite3') as conn:
        conn.execute('DELETE FROM documents')
    client = client_for(configured)
    response = client.post('/api/v1/literature/ask', json={'question':'打浆影响？'})
    record = finished(client, response.json()['id'])
    assert record['status'] == 'refused'
    assert record['reason_code'] == 'empty_library'


def test_worker_deadline_and_error_redaction(configured, monkeypatch):
    def timeout(*args, **kwargs):
        assert args[0][1:4] == ['-I', '-X', 'utf8']
        assert kwargs['timeout'] == 90
        assert 'shell' not in kwargs
        assert json.loads(kwargs['input'])['question'] == '打浆影响？'
        raise subprocess.TimeoutExpired('worker', 90)
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(HTTPException) as error:
        literature.run_answer(configured, '打浆影响？')
    assert error.value.status_code == 504
    monkeypatch.setattr(subprocess, 'run', lambda *a,**k: SimpleNamespace(returncode=1,stdout='',stderr='secret-api-key-and-provider-url'))
    with pytest.raises(HTTPException) as error:
        literature.run_answer(configured, '打浆影响？')
    assert 'secret' not in str(error.value.detail)
    assert error.value.status_code == 503


def test_answer_serialization_and_bad_worker_output(configured, monkeypatch):
    body={'status':'answered','answer':'有依据的回答 [1]','citations':[{'ref':'[1]','document_id':'doc1','page_start':3,'excerpt':'original evidence'}],'latency_ms':20}
    monkeypatch.setattr(subprocess, 'run', lambda *a,**k: SimpleNamespace(returncode=0,stdout=json.dumps(body)))
    client = client_for(configured)
    response = client.post('/api/v1/literature/ask',json={'question':'打浆影响？'})
    record = finished(client, response.json()['id'])
    assert record['result']['answer'] == body['answer']
    assert record['result']['citations'] == body['citations']
    assert record['latency_ms'] is not None
    monkeypatch.setattr(subprocess, 'run', lambda *a,**k: SimpleNamespace(returncode=0,stdout='not-json'))
    response = client.post('/api/v1/literature/ask',json={'question':'打浆影响？'})
    record = finished(client, response.json()['id'])
    assert record['status'] == 'failed'
    assert record['error_status'] == 503


def test_concurrent_question_is_rejected_and_slot_is_released(configured, monkeypatch):
    entered, release = Event(), Event()
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return {'status':'refused','answer':'没有证据','citations':[],'latency_ms':0}
    monkeypatch.setattr(literature, 'run_answer', blocked)
    client = client_for(configured)
    client.get('/api/v1/literature/history')
    with ThreadPoolExecutor(2) as executor:
        future = executor.submit(client.post, '/api/v1/literature/ask', json={'question':'打浆影响？'})
        try:
            assert entered.wait(5)
            assert client.post('/api/v1/literature/ask',json={'question':'第二个问题'}).status_code == 429
        finally:
            release.set()
        response = future.result()
        assert response.status_code == 202
    finished(client, response.json()['id'])
    response = client.post('/api/v1/literature/ask',json={'question':'再问一次'})
    assert response.status_code == 202
    finished(client, response.json()['id'])


def test_post_cors_and_errors_keep_request_id(monkeypatch):
    from app.main import Settings, create_app
    monkeypatch.setenv('LITERATURE_ENABLED', 'false')
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        response = client.options('/api/v1/literature/ask', headers={
            'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        assert response.status_code == 200
        assert 'POST' in response.headers['access-control-allow-methods']
        response = client.post('/api/v1/literature/ask', json={'question':' '})
        assert response.status_code == 422
        assert response.json()['error']['request_id'] == response.headers['X-Request-ID']

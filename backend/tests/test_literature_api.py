import json
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
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
    return literature.LiteratureSettings(_env_file=None, enabled=True, data_dir=tmp_path, engine='legacy', timeout_seconds=90)


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


@pytest.mark.parametrize('stored_path', ['papers/paper.pdf', r'papers\paper.pdf'])
def test_pdf_accepts_portable_imported_paths(configured, stored_path):
    with sqlite3.connect(configured.root / 'metadata.sqlite3') as conn:
        conn.execute('UPDATE documents SET file_path=?', (stored_path,))
    response = client_for(configured).get('/api/v1/literature/documents/doc1/pdf')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.content.startswith(b'%PDF')


@pytest.mark.parametrize('stored_path', ['../outside.pdf', r'..\outside.pdf', r'papers\..\outside.pdf'])
def test_pdf_rejects_traversal_after_separator_normalization(configured, stored_path):
    (configured.root / 'outside.pdf').write_bytes(b'%PDF-1.4\noutside papers')
    with sqlite3.connect(configured.root / 'metadata.sqlite3') as conn:
        conn.execute('UPDATE documents SET file_path=?', (stored_path,))
    assert client_for(configured).get('/api/v1/literature/documents/doc1/pdf').status_code == 404


def test_saved_citation_location_uses_only_matching_mineru_regions(configured):
    chunk_text = 'The quoted original begins here.'
    with sqlite3.connect(configured.root / 'metadata.sqlite3') as conn:
        conn.execute('CREATE TABLE chunks (id TEXT, document_id TEXT, text TEXT)')
        conn.executemany('INSERT INTO chunks VALUES (?,?,?)', [
            ('supported', 'doc1', chunk_text), ('foreign', 'doc2', chunk_text),
        ])
    spans = [
        {'source_id': 'a', 'page': 3, 'bbox': [100, 200, 300, 400]},
        {'source_id': 'b', 'page': 4, 'bbox': [200, 300, 400, 500]},
        {'source_id': 'c', 'page': 4, 'bbox': [200, 300, 400, 500]},
        {'source_id': 'invalid', 'page': 4, 'bbox': [-1, 300, 400, 500]},
        {'source_id': 'out-of-range', 'page': 5, 'bbox': [100, 200, 300, 400]},
    ]
    entry = {'text_sha256': sha256(chunk_text.encode()).hexdigest(), 'source_spans': spans}
    (configured.root / 'structure.json').write_text(json.dumps({
        'mapping': {'supported': entry, 'foreign': entry | {'source_spans': [
            {'source_id': 'foreign', 'page': 3, 'bbox': [0, 0, 1000, 1000]},
        ]}},
    }), encoding='utf-8')
    base = dict(document_id='doc1', page_start=3, page_end=4)
    citations = [
        dict(base, ref='[1]', source_chunks=[
            dict(chunk_id='supported', text=chunk_text),
            dict(chunk_id='foreign', text=chunk_text),
        ]),
        dict(base, ref='[2]', chunk_id='supported', excerpt='changed original'),
        dict(base, ref='[3]', kind='source_image', visual_assets=[
            dict(document_id='doc1', page=4, bbox=[120, 100, 280, 200]),
        ]),
        dict(ref='[4]', kind='experiment_query', document_id=''),
    ]
    store = literature.HistoryStore(configured.root / 'qa_history.sqlite3')
    store.initialize()
    owner, _ = store.session(None)
    history_id = store.create(owner, 'reader-test', '测试引用定位', {})['id']
    store.complete(history_id, dict(status='answered', answer='答案 [1] [2] [3] [4]',
                                    citations=citations), latency_ms=1)
    client = client_for(configured)
    path = f'/api/v1/literature/history/{history_id}/citations'
    assert client.get(f'{path}/1/location').json() == dict(
        document_id='doc1', filename='paper.pdf', page_start=3, page_end=4,
        regions=[dict(page=3, bbox=[100, 200, 300, 400]), dict(page=4, bbox=[200, 300, 400, 500])],
    )
    assert client.get(f'{path}/2/location').json()['regions'] == []
    assert client.get(f'{path}/3/location').json()['regions'] == [dict(page=4, bbox=[120, 100, 280, 200])]
    assert client.get(f'{path}/4/location').status_code == 404
    assert client.get(f'{path}/5/location').status_code == 404


@pytest.mark.parametrize(('excerpt', 'offset', 'pages'), [
    ('second', None, [4]),
    ('end\n\nshared', None, [3, 4]),
    ('shared', None, []),
    ('shared', 20, [4]),
    ('shared', 1, []),
    ('Title', None, []),
])
def test_partial_citation_matches_only_overlapping_regions(configured, excerpt, offset, pages):
    from app.citation_reader import citation_regions

    spans = [
        dict(source_id='a', page=3, bbox=[10, 20, 30, 40], text='shared end'),
        dict(source_id='b', page=4, bbox=[50, 60, 70, 80], text='shared second'),
    ]
    text = '[Title]\n' + '\n\n'.join(span['text'] for span in spans)
    entry = dict(text_sha256=sha256(text.encode()).hexdigest(), source_spans=spans)
    (configured.root / 'structure.json').write_text(json.dumps({'mapping': {'c': entry}}))
    part = dict(chunk_id='c', text=excerpt)
    if offset is not None:
        part.update(start_char=offset, end_char=offset + len(excerpt))
    citation = dict(document_id='doc1', source_chunks=[part])
    with sqlite3.connect(configured.root / 'metadata.sqlite3') as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE chunks (id TEXT, document_id TEXT, text TEXT)')
        conn.execute('INSERT INTO chunks VALUES (?,?,?)', ('c', 'doc1', text))
        regions = citation_regions(conn, configured.root, {}, citation, 3, 4)
    assert [region['page'] for region in regions] == pages


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


def test_calendar_question_uses_beijing_date_without_library_or_model(tmp_path, monkeypatch):
    from literature_rag.application import calendar_answer

    class FixedClock:
        @staticmethod
        def now(tz):
            # Tuesday in UTC has already become Wednesday in Beijing.
            return datetime(2026, 11, 24, 16, 1, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(calendar_answer, 'datetime', FixedClock)
    monkeypatch.setattr(literature, 'run_answer', lambda *args: pytest.fail('Unexpected Agent call'))
    library_lookups = []

    def empty_library(config):
        library_lookups.append(config)
        return []

    monkeypatch.setattr(literature, 'documents', empty_library)
    config = literature.LiteratureSettings(_env_file=None, enabled=True, data_dir=tmp_path, engine='agent')
    client = client_for(config)
    response = client.post('/api/v1/literature/ask', json={'question': '请问，今天星期几？'})
    assert response.status_code == 202
    record = finished(client, response.json()['id'])
    assert record['status'] == 'answered'
    assert record['result']['answer'] == '北京时间今天是2026年11月25日，星期三。'
    assert record['result']['citations'] == []
    assert record['result']['generation_calls'] == []
    assert not library_lookups

    compound = client.post('/api/v1/literature/ask', json={'question': '今天星期几？顺便查一下打浆论文。'})
    assert finished(client, compound.json()['id'])['reason_code'] == 'empty_library'
    assert library_lookups == [config]


def test_worker_deadline_and_error_redaction(configured, monkeypatch):
    def timeout(*args, **kwargs):
        assert args[0][1:4] == ['-I', '-X', 'utf8']
        assert kwargs['timeout'] == 90
        assert 'shell' not in kwargs
        assert json.loads(kwargs['input'])['question'] == '打浆影响？'
        assert json.loads(kwargs['input'])['request_timeout_seconds'] == 90
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

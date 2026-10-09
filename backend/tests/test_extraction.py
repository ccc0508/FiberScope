import copy
import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import extraction
from app.literature import LiteratureSettings, router
from literature_extraction import Payload, ExtractionError, ground, extract, snapshot

BASE = '/api/v1/literature/extractions'
EVIDENCE = {'pdf_sha256': 'a'*64, 'page': 1, 'words': [
    {'id': 'w1', 'text': 'Table', 'bbox': [10, 5, 30, 12]},
    {'id': 'w2', 'text': '3', 'bbox': [32, 5, 36, 12]},
    {'id': 'w3', 'text': 'fiberlength', 'bbox': [100, 15, 150, 22]},
    {'id': 'w4', 'text': '(mm)', 'bbox': [110, 25, 135, 32]},
    {'id': 'w5', 'text': 'tensileindex', 'bbox': [160, 15, 215, 22]},
    {'id': 'w6', 'text': '(N·m/g)', 'bbox': [160, 25, 200, 32]},
    {'id': 'w7', 'text': 'unrefined', 'bbox': [160, 35, 200, 42]},
    {'id': 'w8', 'text': 'bagasse', 'bbox': [10, 50, 40, 57]},
    {'id': 'w9', 'text': '1.36', 'bbox': [110, 50, 130, 57]},
    {'id': 'w10', 'text': '58.96', 'bbox': [160, 50, 180, 57]},
]}
MODEL = {'columns': [
    {'key': 'c1', 'metric': 'fiber_length', 'header_word_ids': ['w3'], 'unit': 'mm', 'unit_word_ids': ['w4'], 'state': 'raw_material', 'state_word_ids': []},
    {'key': 'c2', 'metric': 'tensile_index', 'header_word_ids': ['w5'], 'unit': 'N·m/g', 'unit_word_ids': ['w6'], 'state': 'unrefined', 'state_word_ids': ['w7']},
], 'rows': [{'raw_material': 'bagasse', 'label_word_ids': ['w8'], 'cells': {'c1': 'w9', 'c2': 'w10'}}], 'warnings': []}


def test_literal_values_positions_and_pending_state():
    result = ground(Payload.model_validate(MODEL), EVIDENCE, 'Table 3')
    assert result['measurement_count'] == 2
    assert result['measurements'][0]['value'] == 1.36
    assert result['measurements'][1]['raw_value'] == '58.96'
    assert result['measurements'][1]['source_bbox_pt'] == [160, 50, 180, 57]
    assert not result['approved_for_training']
    assert all(r['human_review_status'] == 'pending' for r in result['measurements'])


@pytest.mark.parametrize('change,reason', [
    (lambda p: p['rows'][0]['cells'].update(c1='invented'), 'invalid_evidence_reference'),
    (lambda p: p['columns'][0].update(unit='cm'), 'unsupported_unit'),
    (lambda p: p['columns'][1].update(state='refined'), 'unsupported_state'),
    (lambda p: p['rows'][0].update(raw_material='bamboo'), 'unsupported_row_label'),
    (lambda p: p['rows'][0]['cells'].update(c1='w10'), 'reused_numeric_word'),
    (lambda p: p['rows'][0]['cells'].pop('c2'), 'missing_column_key'),
    (lambda p: p['rows'].append(copy.deepcopy(p['rows'][0])), 'duplicate_row'),
    (lambda p: p['columns'][1].update(key='c1'), 'duplicate_column'),
])
def test_rejects_ungrounded_or_ambiguous_output(change, reason):
    model = copy.deepcopy(MODEL)
    change(model)
    with pytest.raises(ExtractionError, match=reason):
        ground(Payload.model_validate(model), EVIDENCE, 'Table 3')


def test_missing_cell_remains_missing_and_no_unit_inference():
    model = copy.deepcopy(MODEL)
    model['rows'][0]['cells']['c2'] = None
    model['columns'][0].update(unit='', unit_word_ids=[])
    result = ground(Payload.model_validate(model), EVIDENCE, 'Table 3')
    assert result['measurement_count'] == 1
    assert result['measurements'][0]['raw_unit'] == ''
    assert result['warnings'] == ['missing_or_unsupported_cell:row=1,column=c2']


def test_row_position_check():
    evidence = copy.deepcopy(EVIDENCE)
    evidence['words'][-1]['bbox'][1] = 200
    with pytest.raises(ExtractionError, match='row_position_mismatch'):
        ground(Payload.model_validate(MODEL), evidence, 'Table 3')


def test_generation_repair_usage_and_no_benchmark_input():
    calls, checkpoints = [], []
    def generate(**kwargs):
        calls.append(kwargs)
        bad = copy.deepcopy(MODEL)
        bad['rows'][0]['cells']['c1'] = 'invented'
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(bad if len(calls)==1 else MODEL)))],
                               usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=generate)))
    result = extract(EVIDENCE, 'Table 3', SimpleNamespace(llm_model='fixture'), client, checkpoints.append)
    assert len(calls) == 2 and len(result['generation_calls']) == 2
    assert result['generation_calls'][0]['validation_error'] == 'invalid_evidence_reference'
    assert result['generation_calls'][1]['usage']['total_tokens'] == 30
    assert all('264' not in c['messages'][1]['content'] for c in calls)
    with pytest.raises(ExtractionError, match='table_not_found'):
        extract(EVIDENCE, 'Table 9', SimpleNamespace(llm_model='fixture'), client)


def test_invalid_pdf_is_redacted(tmp_path):
    path = tmp_path / 'bad.pdf'
    path.write_bytes(b'%PDF-1.4 secret-private-error')
    with pytest.raises(ExtractionError, match='invalid_pdf') as error:
        snapshot(path, 1, None)
    assert 'secret' not in str(error.value)


@pytest.fixture
def configured(tmp_path):
    return LiteratureSettings(_env_file=None, enabled=True, data_dir=tmp_path, extraction_timeout_seconds=10)


def finish(client, record_id):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        response = client.get(BASE + '/' + record_id)
        assert response.status_code == 200
        record = response.json()
        if record['status'] != 'processing':
            return record
        sleep(.01)
    raise AssertionError('job did not finish')


def app_for(config):
    app = FastAPI()
    app.include_router(router(config))
    return app


def success(config, pdf, source, artifact):
    evidence = {**EVIDENCE, 'pdf_sha256': source['pdf_sha256']}
    (artifact / 'evidence.json').write_text(json.dumps(evidence), encoding='utf8')
    (artifact / 'result.json').write_text(json.dumps(ground(Payload.model_validate(MODEL), EVIDENCE, source['table'])), encoding='utf8')
    (artifact / 'configuration.json').write_text(json.dumps({'llm_model': 'fixture'}), encoding='utf8')
    return {'ok': True}


def submit(client, key=None, **params):
    return client.post(BASE, params={'page': 1, 'table': 'Table 3', 'request_id': str(key or uuid4()), **params},
                       content=b'%PDF-1.4 fake', headers={'Content-Type': 'application/pdf'})


def test_http_public_records_pdf_export_idempotency_and_restart(configured, monkeypatch):
    monkeypatch.setattr(extraction, 'run_worker', success)
    app = app_for(configured)
    with TestClient(app) as client:
        key = uuid4()
        response = submit(client, key)
        assert response.status_code in (200,202)
        assert 'HttpOnly' in response.headers['set-cookie']
        record = finish(client, response.json()['id'])
        assert record['status'] == 'completed' and record['snapshot']['result']['measurement_count'] == 2
        assert submit(client, key).json()['id'] == record['id']
        assert submit(client, key, page=2).status_code == 409
        assert client.get(BASE).json()['pagination']['total'] == 1
        exported = client.get(BASE + '/' + record['id'] + '/export')
        assert exported.headers['cache-control'] == 'no-store'
        assert json.loads(exported.text)['snapshot']['result']['measurement_count'] == 2
        assert int(exported.headers['content-length']) == len(exported.content)
        assert 'owner_id' not in exported.text and 'request_key' not in exported.text
        pdf = client.get(BASE + '/' + record['id'] + '/pdf')
        assert pdf.content.startswith(b'%PDF-')
        assert int(pdf.headers['content-length']) == len(pdf.content)
        stranger = TestClient(app)
        assert stranger.get(BASE).json()['pagination']['total'] == 1
        assert record['can_review'] is True
        for suffix in ['', '/pdf', '/export']:
            assert stranger.get(BASE + '/' + record['id'] + suffix).status_code == 200
        assert stranger.get(BASE + '/' + record['id']).json()['can_review'] is False
        stranger.cookies.clear()
        assert stranger.get(BASE + '/' + record['id']).json()['snapshot'] == record['snapshot']
        saved_cookie = client.cookies.get('fiber_extraction_session')
    with TestClient(app_for(configured)) as refreshed:
        assert refreshed.get(BASE + '/' + record['id']).json()['snapshot'] == record['snapshot']
        assert refreshed.get(BASE + '/' + record['id']).json()['can_review'] is False
        refreshed.cookies.set('fiber_extraction_session', saved_cookie, path=BASE)
        assert refreshed.get(BASE + '/' + record['id']).json()['can_review'] is True


def test_public_list_includes_multiple_submitters_and_keys_remain_owned(configured, monkeypatch):
    monkeypatch.setattr(extraction, 'run_worker', success)
    app=app_for(configured)
    with TestClient(app) as first:
        key=uuid4()
        a=finish(first,submit(first,key).json()['id'])
        second=TestClient(app)
        b=finish(second,submit(second,key).json()['id'])
        assert a['id'] != b['id']
        assert submit(second,key).json()['id'] == b['id']
        shared=first.get(BASE,params={'page_size':1}).json()
        assert shared['pagination']['total']==2 and shared['pagination']['total_pages']==2
        assert second.get(f"{BASE}/{a['id']}").json()['can_review'] is False
        assert second.get(f"{BASE}/{b['id']}").json()['can_review'] is True


def test_background_concurrency_and_origin(configured, monkeypatch):
    entered, release = Event(), Event()
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return success(*args)
    monkeypatch.setattr(extraction, 'run_worker', blocked)
    with TestClient(app_for(configured)) as client:
        key = uuid4()
        response = submit(client, key)
        assert entered.wait(5)
        try:
            assert submit(client, key).json()['id'] == response.json()['id']
            assert submit(client).status_code == 429
            assert client.get(BASE + '/' + response.json()['id']).json()['status'] == 'processing'
            bad = client.post(BASE, params={'page':1,'table':'Table 3'}, content=b'%PDF-1.4',
                              headers={'Content-Type':'application/pdf','Origin':'https://evil.example'})
            assert bad.status_code == 403
        finally:
            release.set()
        assert finish(client, response.json()['id'])['status'] == 'completed'


@pytest.mark.parametrize('reason', ['timeout', 'invalid_pdf', 'text_unavailable', 'provider_error', 'validation_failed'])
def test_failure_evidence_is_saved(configured, monkeypatch, reason):
    def fail(config,pdf,source,artifact):
        (artifact/'evidence.json').write_text(json.dumps(EVIDENCE), encoding='utf8')
        return {'ok': False, 'reason': reason}
    monkeypatch.setattr(extraction, 'run_worker', fail)
    with TestClient(app_for(configured)) as client:
        record = finish(client, submit(client).json()['id'])
        assert record['status'] == 'failed' and record['reason_code'] == reason
        assert record['snapshot']['evidence'] == EVIDENCE


def test_validation_limits_and_disabled(configured):
    with TestClient(app_for(configured)) as client:
        assert client.post(BASE,params={'page':1,'table':'Table 3'},content=b'bad',headers={'Content-Type':'application/pdf'}).status_code==422
        assert client.post(BASE,params={'page':1,'table':'Table 3'},content=b'%PDF-').status_code==415
        assert submit(client,page=0).status_code==422
        assert submit(client,table='DROP TABLE x').status_code==422
        assert submit(client,crop='0,0,nan,100').status_code==422
        assert submit(client,crop='2,2,1,1').status_code==422
        assert client.post(BASE,params={'page':1,'table':'Table 3'},content=b'%PDF-'+b'0'*extraction.MAX_PDF_BYTES,headers={'Content-Type':'application/pdf'}).status_code==413
    with TestClient(app_for(LiteratureSettings(_env_file=None,enabled=False,data_dir=configured.root))) as disabled:
        assert disabled.get(BASE).status_code==503


def test_restart_marks_processing_interrupted_and_multiple_process_guard(configured):
    first = extraction.ExtractionRunner(configured)
    first.ensure()
    owner,_ = first.store.session(None)
    record_id = first.store.create(owner,str(uuid4()),'fingerprint',{'filename':'paper.pdf'})
    artifact = first.root / 'jobs' / record_id
    artifact.mkdir(parents=True)
    (artifact / 'evidence.json').write_text(json.dumps(EVIDENCE), encoding='utf8')
    second = extraction.ExtractionRunner(configured)
    with pytest.raises(Exception) as e:
        second.ensure()
    assert e.value.status_code==503
    first.close()
    second.ensure()
    try:
        assert second.store.get(owner,record_id)['status']=='interrupted'
        assert second.store.get(owner,record_id)['snapshot']['evidence']==EVIDENCE
    finally:
        second.close()


def test_save_failure_is_reported_not_completed(configured,monkeypatch):
    runner=extraction.ExtractionRunner(configured)
    runner.ensure()
    owner,_=runner.store.session(None)
    entered=Event()
    def broken(*args):
        entered.set()
        raise extraction.sqlite3.OperationalError('private database path')
    monkeypatch.setattr(runner.store,'finish',broken)
    monkeypatch.setattr(extraction,'run_worker',success)
    source={'filename':'paper.pdf','pdf_sha256':'a'*64,'page':1,'table':'Table 3','crop':None}
    record_id=runner.submit(owner,str(uuid4()),source,b'%PDF-1.4',monotonic())
    assert entered.wait(5)
    runner.close()
    assert record_id in runner.save_errors


def test_source_change_is_rejected(configured,monkeypatch):
    def tampered(config,pdf,source,artifact):
        success(config,pdf,source,artifact)
        (artifact / 'evidence.json').write_text(json.dumps(EVIDENCE), encoding='utf8')
        return {'ok':True}
    monkeypatch.setattr(extraction,'run_worker',tampered)
    with TestClient(app_for(configured)) as client:
        record=finish(client,submit(client).json()['id'])
        assert record['status']=='failed' and record['reason_code']=='source_changed'


def test_numeric_reference_cannot_be_paragraph_text():
    from literature_extraction import number
    assert number('1,200')==1200
    for value in ['nan','inf','text','1.2±0.1','1e101']:
        with pytest.raises(ExtractionError):
            number(value)


def test_eval_detects_missing_duplicate_unit_position_and_wrong_version(tmp_path):
    from literature_extraction_eval import evaluate
    import csv
    folder=tmp_path/'benchmark'
    folder.mkdir()
    (folder/'metadata.json').write_text(json.dumps({'benchmark_id':'test','source_pdf_sha256':'a'*64,'source_pdf_page':1,'source_table':'Table 3'}))
    reference=[{'raw_material_original':'bagasse','metric':'fiber_length','measurement_state':'raw_material','raw_value':'1.36','raw_unit':'mm','source_bbox_pt':'[110,50,130,57]'}]
    with (folder/'table3_measurements.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(reference[0]))
        writer.writeheader(); writer.writerows(reference)
    records=ground(Payload.model_validate(MODEL),EVIDENCE,'Table 3')['measurements'][:1]
    task={'id':'test','status':'completed','source':{'pdf_sha256':'a'*64,'page':1,'table':'Table 3'},'snapshot':{'result':{'measurements':records}}}
    assert evaluate(task,folder)['correct_measurements']==1
    records.append(copy.deepcopy(records[0]))
    assert evaluate(task,folder)['duplicate_extra_count']==1
    records.pop(); records[0]['raw_unit']='cm'
    assert evaluate(task,folder)['incorrect'][0]['issues']==['unit']
    records[0]['source_bbox_pt']=[1,2,3,4]
    assert 'source_position' in evaluate(task,folder)['incorrect'][0]['issues']
    records.clear()
    assert evaluate(task,folder)['missing_count']==1
    task['source']['pdf_sha256']='b'*64
    with pytest.raises(ValueError): evaluate(task,folder)

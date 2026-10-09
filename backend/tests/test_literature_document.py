import copy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import literature_document as document
from literature_extraction import ExtractionError
from app import extraction
from tests.test_extraction import EVIDENCE, MODEL, app_for, configured, finish

PAGE = {**EVIDENCE, 'page_count': 2, 'width_pt': 612, 'height_pt': 792}
TEXT = {'label_word_ids': ['w8'], 'metric': 'fiber_length', 'header_word_ids': ['w3'],
        'value_word_id': 'w9', 'unit': 'mm', 'unit_word_ids': ['w4'],
        'state': 'raw_material', 'state_word_ids': [], 'context_word_ids': ['w3','w4','w8','w9']}
TABLE = {'title_word_ids': ['w1','w2'], 'bbox': [0,0,300,100], 'reason': '原料形态和纸张强度数据'}


def fixture_client(outputs):
    requests = []
    def create(**args):
        requests.append(args)
        output = outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(output)))],
                               usage=SimpleNamespace(total_tokens=123))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), requests


def test_model_discovers_tables_without_user_page_or_table_and_reads_whole_page():
    client, requests = fixture_client([{'tables':[TABLE], 'text_measurements':[], 'notes':[]}])
    found, calls = document.discover(PAGE, SimpleNamespace(llm_model='fixture'), client)
    assert found.tables[0].title_word_ids == ['w1','w2']
    prompt = json.loads(requests[0]['messages'][1]['content'])
    assert len(prompt['words']) == len(PAGE['words'])
    assert 'target_table' not in prompt
    assert calls[0]['usage']['total_tokens'] == 123


@pytest.mark.parametrize('change,reason', [
    (lambda p:p['text_measurements'][0].update(value_word_id='invented'), 'invalid_evidence_reference'),
    (lambda p:p['text_measurements'][0].update(unit='cm'), 'unsupported_unit'),
    (lambda p:p['text_measurements'][0].update(state='refined',state_word_ids=['w7'],context_word_ids=['w3','w4','w7','w8','w9']), 'unsupported_state'),
    (lambda p:p['text_measurements'][0].update(context_word_ids=['w9']), 'unsupported_prose_context'),
    (lambda p:p['tables'].append({**TABLE,'bbox':[0,0,999,100]}), 'invalid_crop'),
    (lambda p:p['text_measurements'][0].update(value_word_id='w3',context_word_ids=['w3','w4','w8','w9']), 'unsupported_numeric_cell'),
])
def test_prose_and_regions_require_literal_local_evidence(change, reason):
    value = {'tables':[], 'text_measurements':[copy.deepcopy(TEXT)], 'notes':[]}
    change(value)
    with pytest.raises(ExtractionError, match=reason):
        document.validate_discovery(document.Discovery.model_validate(value), PAGE)


def test_prose_quotes_and_dedup_never_copy_table_numbers_or_infer_training_approval():
    found = document.Discovery.model_validate({'tables':[], 'text_measurements':[TEXT,TEXT], 'notes':[]})
    records = document.prose_records(found, PAGE)
    assert len(records) == 1
    assert records[0]['raw_value'] == '1.36' and records[0]['source_pdf_page'] == 1
    assert records[0]['source_kind'] == 'text' and 'bagasse' in records[0]['source_quote']
    assert records[0]['human_review_status'] == 'pending'
    found.tables.append(document.TableRegion.model_validate(TABLE))
    assert document.prose_records(found, PAGE) == []


def test_glued_header_units_are_literal_not_inferred():
    from literature_extraction import unit_supported
    assert unit_supported('%',[{'text':'pulpyield(%)'}])
    assert unit_supported('mm',[{'text':'fiberlength(mm)'}])
    assert not unit_supported('cm',[{'text':'fiberlength(mm)'}])
    assert not unit_supported('%',[{'text':'flexibilitycoefficient'}])


def test_prose_scalar_joined_units_preserve_approximation_and_reject_ranges():
    from literature_extraction import literal_numeric_parts
    assert literal_numeric_parts('~60g/m2') == ('60','g/m2','approximate')
    assert literal_numeric_parts('170°C') == ('170','°C','unspecified')
    for value in ['60±3','10–20','R2=0.8','NaOH17.5%']:
        with pytest.raises(ExtractionError): literal_numeric_parts(value)
    page=copy.deepcopy(PAGE)
    page['words'][8]['text']='~60g/m2'
    found=document.Discovery.model_validate({'tables':[], 'text_measurements':[
        {**TEXT,'unit':'g/m2','unit_word_ids':['w9']}], 'notes':[]})
    document.validate_discovery(found,page)
    r=document.prose_records(found,page)[0]
    assert r['raw_value']=='60' and r['source_value_text']=='~60g/m2'
    assert r['value_qualifier']=='approximate' and r['raw_unit']=='g/m2'


def test_separate_about_word_is_preserved_as_approximation():
    page=copy.deepcopy(PAGE)
    page['words'].append({'id':'w11','text':'about','bbox':[85,50,108,57]})
    found=document.Discovery.model_validate({'tables':[], 'text_measurements':[
        {**TEXT,'context_word_ids':[*TEXT['context_word_ids'],'w11']}], 'notes':[]})
    document.validate_discovery(found,page)
    assert document.prose_records(found,page)[0]['value_qualifier']=='approximate'


def test_repair_keeps_failed_call_usage_and_original_words():
    bad = {'tables':[], 'text_measurements':[{**TEXT, 'unit':'cm'}], 'notes':[]}
    good = {'tables':[], 'text_measurements':[TEXT], 'notes':[]}
    client, requests = fixture_client([bad, good])
    saved = []
    _, calls = document.discover(PAGE, SimpleNamespace(llm_model='fixture'), client,
                                 lambda c:saved.append(copy.deepcopy(c)))
    assert len(requests) == 2 and calls[0]['validation_error'] == 'unsupported_unit'
    assert saved[-1] == calls
    assert 'unsupported_unit' in requests[1]['messages'][1]['content']


def fake_pdf(monkeypatch, tmp_path, pages=2):
    import pdfplumber
    class PDF:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        @property
        def pages(self): return [None]*pages
    monkeypatch.setattr(pdfplumber,'open',lambda _:PDF())
    monkeypatch.setattr(document,'snapshot',lambda path,page,crop,**kwargs:{**PAGE,'page':page,'page_count':pages})
    path=tmp_path/'paper.pdf'
    path.write_bytes(b'%PDF-fixture')
    return path


def test_all_pages_tables_prose_distinct_ids_checkpoints_and_no_cross_page_join(monkeypatch,tmp_path):
    path=fake_pdf(monkeypatch,tmp_path)
    client, requests=fixture_client([
        {'tables':[TABLE],'text_measurements':[],'notes':[]}, MODEL,
        {'tables':[],'text_measurements':[TEXT],'notes':['图中读数需人工处理']},
    ])
    saved={}
    result=document.extract_document(path,SimpleNamespace(llm_model='fixture'),
                                      lambda k,v:saved.update({k:copy.deepcopy(v)}),client=client)
    assert len(requests)==3 and result['measurement_count']==3
    assert len({r['record_id'] for r in result['measurements']})==3
    assert [c['page'] for c in result['coverage']]==[1,2]
    assert result['coverage_complete']
    assert saved['progress.json']['page']==2
    assert set(saved['evidence.json']['pages'])=={'1','2'}
    assert len(saved['diagnostics.json']['generation_calls'])==3
    assert all(r['human_review_status']=='pending' for r in result['measurements'])
    assert any('图中读数' in w for w in result['warnings'])
    assert result['approved_for_training'] is False


def test_failed_page_and_failed_table_are_visible_not_successful_coverage(monkeypatch,tmp_path):
    path=fake_pdf(monkeypatch,tmp_path)
    client,_=fixture_client([
        {'tables':[TABLE],'text_measurements':[],'notes':[]}, RuntimeError('private supplier error'),
        RuntimeError('private supplier error'),
    ])
    result=document.extract_document(path,SimpleNamespace(llm_model='fixture'),lambda *_:None,client=client)
    assert not result['coverage_complete'] and result['measurement_count']==0
    assert result['discovered_tables'][0]['error_code']=='provider_error'
    assert result['coverage'][1]['status']=='failed'
    assert 'private supplier error' not in json.dumps(result)


def test_budget_never_silently_skips_pages(monkeypatch,tmp_path):
    path=fake_pdf(monkeypatch,tmp_path)
    client,requests=fixture_client([])
    result=document.extract_document(path,SimpleNamespace(llm_model='fixture'),lambda *_:None,
                                      budget_seconds=1,client=client)
    assert requests==[] and len(result['coverage'])==2
    assert all(c['reason']=='budget_exhausted' for c in result['coverage'])
    assert not result['coverage_complete']


@pytest.mark.parametrize('during_table',[False,True])
def test_balance_exhaustion_stops_further_calls_and_reports_remaining_pages(monkeypatch,tmp_path,during_table):
    path=fake_pdf(monkeypatch,tmp_path,3)
    class NoBalance(Exception):
        status_code=402
    outputs=[NoBalance('private provider details')]
    if during_table:
        outputs.insert(0,{'tables':[TABLE,TABLE],'text_measurements':[],'notes':[]})
    client,requests=fixture_client(outputs)
    result=document.extract_document(path,SimpleNamespace(llm_model='fixture'),lambda *_:None,client=client)
    assert len(requests)==(2 if during_table else 1)
    assert [c['status'] for c in result['coverage']]==(['scanned','skipped','skipped'] if during_table else ['failed','skipped','skipped'])
    if during_table:
        assert len(result['discovered_tables'])==2
        assert all(t['error_code']=='model_balance_exhausted' for t in result['discovered_tables'])
    else:
        assert result['coverage'][0]['reason']=='model_balance_exhausted'
    assert not result['coverage_complete']
    assert any('余额不足' in w for w in result['warnings'])
    assert 'private provider details' not in json.dumps(result)


def test_document_http_default_idempotency_private_review_and_page_routing(configured,monkeypatch):
    def worker(config,pdf,source,artifact):
        assert source['mode']=='document' and source['page'] is None
        evidence={**PAGE,'pdf_sha256':source['pdf_sha256']}
        measurement=document.prose_records(document.Discovery.model_validate(
            {'tables':[],'text_measurements':[TEXT],'notes':[]}),evidence)[0]
        (artifact/'evidence.json').write_text(json.dumps({'pdf_sha256':source['pdf_sha256'],
            'page_count':2,'pages':{'1':evidence}}))
        (artifact/'result.json').write_text(json.dumps({'measurements':[measurement],'measurement_count':1}))
        return {'ok':True}
    monkeypatch.setattr(extraction,'run_worker',worker)
    base='/api/v1/literature/extractions'
    app = app_for(configured)
    with TestClient(app) as client:
        key=str(uuid4())
        params={'request_id':key}
        headers={'Content-Type':'application/pdf'}
        response=client.post(base,params=params,content=b'%PDF-fake',headers=headers)
        assert response.status_code in (200,202)
        task=finish(client,response.json()['id'])
        assert task['status']=='completed' and task['source']['mode']=='document'
        assert client.post(base,params=params,content=b'%PDF-fake',headers=headers).json()['id']==task['id']
        assert client.post(base,params={**params,'mode':'table','page':1,'table':'Table 3'},content=b'%PDF-fake',headers=headers).status_code==409
        for args in ({'mode':'table'}, {'mode':'document','page':1}, {'mode':'document','table':'Table 3'}):
            assert client.post(base,params=args,content=b'%PDF-fake',headers=headers).status_code==422
        assert client.get(f'{base}/{task["id"]}/page').status_code==422
        assert client.get(f'{base}/{task["id"]}/page?page=3').status_code==422
        stranger = TestClient(app)
        assert stranger.get(f'{base}/{task["id"]}/page?page=1').status_code==404


def test_atomic_checkpoint_retries_brief_windows_reader_lock(monkeypatch,tmp_path):
    from extraction_worker import save_artifact
    import extraction_worker
    original=Path.replace
    attempts=[]
    def locked_once(path,target):
        attempts.append(target)
        if len(attempts)<3: raise PermissionError('reader still open')
        return original(path,target)
    monkeypatch.setattr(Path,'replace',locked_once)
    monkeypatch.setattr(extraction_worker,'sleep',lambda _:None)
    save_artifact(tmp_path,'progress.json',{'page':2})
    assert json.loads((tmp_path/'progress.json').read_text())=={'page':2}
    assert len(attempts)==3 and not (tmp_path/'progress.json.tmp').exists()


def test_failed_grounded_partial_result_reviewable_but_changed_source_is_not(configured,monkeypatch):
    from tests.test_extraction import success,submit,BASE
    def partial(*args):
        success(*args)
        return {'ok':False,'reason':'model_balance_exhausted'}
    monkeypatch.setattr(extraction,'run_worker',partial)
    with TestClient(app_for(configured)) as client:
        task=finish(client,submit(client).json()['id'])
        assert task['status']=='failed' and task['has_reviewable_result']
        m=task['snapshot']['result']['measurements'][0]
        body={'expected_revision':0,**{k:m[k] for k in ('raw_material','metric','measurement_state','raw_value','raw_unit')},'status':'confirmed','note':'Partial extraction reviewed against source','suitability':'unassessed'}
        assert client.post(f'{BASE}/{task["id"]}/reviews/{m["record_id"]}',json=body).status_code==200
        assert len(client.get(f'{BASE}/{task["id"]}/confirmed').text.splitlines())==1
    def changed(*args):
        success(*args)
        return {'ok':False,'reason':'source_changed'}
    monkeypatch.setattr(extraction,'run_worker',changed)
    with TestClient(app_for(configured)) as client:
        task=finish(client,submit(client).json()['id'])
        assert not task['has_reviewable_result']
        assert client.post(f'{BASE}/{task["id"]}/reviews/{m["record_id"]}',json=body).status_code==409

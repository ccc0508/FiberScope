import json
from types import SimpleNamespace
from pathlib import Path
from hashlib import sha256

import pytest
from literature_rag.application.tools import LiteratureTools,ToolTraceStore
from literature_rag.domain.models import Chunk,VisualAsset,Evidence

@pytest.fixture
def kit(tmp_path):
    chunks=[Chunk(str(i),'doc','paper.pdf',i+1,i+1,i,'x'*300,100,'test',kind='table' if i==1 else 'text') for i in range(3)]
    catalog=SimpleNamespace(chunks={c.id:c for c in chunks},mapping={c.id:dict(section_id='s',section_path=['Section'],content_role='table' if c.id=='1' else 'body') for c in chunks})
    r=SimpleNamespace(body_context_catalog=catalog,visual_catalog=SimpleNamespace(assets=[]),retrieve=lambda *a:[Evidence('[1]','0','doc','paper.pdf',1,1,'x'*300,.9)])
    return LiteratureTools(r,tmp_path,ToolTraceStore(tmp_path/'traces.db'))

def test_search_keeps_pipeline_and_trace(kit):
    out=kit.call(dict(tool='search_literature',query='q',reason='find evidence'),run_id='run')
    assert out['result']['evidence'][0]['locator']['section_id']=='s'
    record=kit.store.read('run')[0]
    assert record['status']=='completed' and record['input']['query']=='q'
    assert record['result']==out['result']

def test_section_pagination_and_dedup(kit):
    p=dict(tool='read_section',document_id='doc',section_id='s',max_chars=256,exclude_chunk_ids=['0'],reason='context')
    texts=[];offset=0
    while True:
        out=kit.call(dict(p,offset=offset),run_id='run')['result']
        texts.extend(s['text'] for s in out['sources'])
        if out['next_offset'] is None:break
        offset=out['next_offset']
    assert len(''.join(texts))==600
    assert len(kit.store.read('run'))==3

def test_table_checks_document_and_role(kit):
    p=dict(tool='read_table',document_id='doc',chunk_id='1',reason='table')
    assert kit.call(p,run_id='r')['result']['table']['text']=='x'*300
    assert kit.call(dict(p,document_id='other'),run_id='r')['status']=='failed'
    assert kit.call(dict(p,chunk_id='0'),run_id='r')['status']=='failed'

def test_invalid_args_do_not_persist_extra_fields(kit):
    out=kit.call(dict(tool='search_literature',query='q',reason='r',api_key='private'),run_id='r')
    assert out['status']=='invalid_arguments'
    assert 'private' not in json.dumps(kit.store.read('r'))

def test_failure_redacts_provider_error_and_records(kit):
    def fail(*a):raise RuntimeError('secret upstream error')
    kit.retriever.retrieve=fail
    assert kit.call(dict(tool='search_literature',query='q',reason='r'),run_id='r')['status']=='failed'
    assert 'secret' not in json.dumps(kit.store.read('r'))

def test_image_integrity_and_delivery(kit):
    data=b'\x89PNG\r\n\x1a\ntest';digest=sha256(data).hexdigest()
    path=kit.root/'visual-assets'/f'{digest}.png';path.parent.mkdir();path.write_bytes(data)
    a=VisualAsset('image','doc','1','Table 1',2,(0,0,10,10),f'visual-assets/{digest}.png',digest,10,10,len(data))
    kit.retriever.visual_catalog.assets=[a]
    p=dict(tool='view_image',document_id='doc',asset_id='image',reason='check pixels')
    out=kit.call(p,run_id='r');assert out['image']['base64']
    assert 'base64' not in json.dumps(kit.store.read('r'))
    path.write_bytes(b'changed')
    assert kit.call(p,run_id='r')['status']=='failed'

def test_interrupted_record_remains_visible(kit):
    kit.store.save(dict(call_id='c',run_id='r',status='started'))
    assert kit.store.read('r')[0]['status']=='started'

def test_calculation_and_provenance(kit):
    source=kit.call(dict(tool='read_table',document_id='doc',chunk_id='1',reason='values'),run_id='r')
    p=dict(tool='calculate_change',initial='47.16',final='42.35',unit='%',source_call_ids=[source['call_id']],reason='compute change')
    result=kit.call(p,run_id='r')['result']
    assert result['difference']=='-4.81'
    assert float(result['relative_change_percent'])==pytest.approx(-10.1993214588)
    assert kit.call(dict(p,initial='0'),run_id='r')['result']['relative_change_percent'] is None
    assert kit.call(p,run_id='other')['status']=='failed'

def test_ledger_dedup_content_change_and_run_isolation(kit):
    p=dict(tool='search_literature',query='q',reason='search')
    first=kit.call(p,run_id='r');second=kit.call(p,run_id='r')
    assert first['result']['evidence'][0]['ref']==second['result']['evidence'][0]['ref']=='[1]'
    assert len(kit.store.evidence('r')[0]['call_ids'])==2
    kit.retriever.retrieve=lambda *a:[Evidence('[1]','0','doc','paper.pdf',1,1,'changed',.8)]
    third=kit.call(p,run_id='r')
    assert third['result']['evidence'][0]['ref']=='[2]'
    assert kit.store.evidence('r',['[1]'])[0]['content']['text']=='x'*300
    assert kit.call(p,run_id='other')['result']['evidence'][0]['ref']=='[1]'
    with pytest.raises(LookupError):kit.store.evidence('other',['[2]'])
    assert ToolTraceStore(kit.store.path).evidence('r')==kit.store.evidence('r')

def test_same_full_text_cross_tool_reuses_identity(kit):
    first=kit.call(dict(tool='search_literature',query='q',reason='s'),run_id='r')
    second=kit.call(dict(tool='read_section',document_id='doc',section_id='s',max_chars=600,reason='read'),run_id='r')
    assert first['result']['evidence'][0]['ref']==second['result']['sources'][0]['ref']
    table=kit.call(dict(tool='read_table',document_id='doc',chunk_id='1',reason='table'),run_id='r')
    assert table['result']['table']['ref']==second['result']['sources'][1]['ref']

def test_ledger_concurrent_numbering(kit):
    from concurrent.futures import ThreadPoolExecutor
    def one(i):
        record=dict(call_id=str(i),run_id='r',status='completed',input=dict(tool='view_image'),
            result=dict(asset=dict(id=str(i),document_id='doc'),image_sha256=str(i),image_bytes=1))
        kit.store.complete(record)
        return record['result']['ref']
    with ThreadPoolExecutor(max_workers=4) as pool:refs=list(pool.map(one,range(12)))
    assert len(set(refs))==12
    assert [r['ref'] for r in kit.store.evidence('r')]==[f'[{i}]' for i in range(1,13)]

def test_failed_registration_rolls_back_snapshot_and_completion(kit):
    r=dict(call_id='bad',run_id='r',status='started')
    kit.store.save(r)
    r.update(status='completed',input=dict(tool='search_literature'),result=dict(evidence=[
        dict(ref='[1]',chunk_id='0',document_id='doc',filename='p',page_start=1,page_end=1,text='ok'),
        dict(ref='[2]')]))
    with pytest.raises(KeyError):kit.store.complete(r)
    assert kit.store.evidence('r')==[]
    assert kit.store.read('r')[0]['status']=='started'

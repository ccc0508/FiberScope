from copy import deepcopy
from literature_rag.application.agent_context import EvidenceProjection


def payload(ref,text,document='d'):
    return dict(status='completed',call_id='c',result=dict(evidence=[dict(
        ref=ref,document_id=document,chunk_id='chunk',text=text,
        source_chunks=[dict(text='unnecessary duplicate')],source_locators={'chunk':{}},
        locator=dict(section_id='s'),visual_assets=[dict(id='img',document_id=document,label='Figure 1',image_path='private')])]))


def restore(e,parts):
    result=[]
    for p in e['text_parts']:
        if 'text_id' in p:parts[p['text_id']]=p['text']
        result.append(parts[p['reuse_text_id']] if 'reuse_text_id' in p else p['text'])
    return ''.join(result)


def test_exact_overlap_keeps_ref_provenance_and_reconstructs_all_text():
    projector=EvidenceProjection();cache={}
    a='A'*100+'\n\n';b='B'*100+'\n';c='C'*100
    raw=payload('[1]',a+b);original=deepcopy(raw)
    first=projector.project(raw)['result']['evidence'][0]
    assert raw==original and 'source_chunks' not in first and 'source_locators' not in first
    assert first['locator']['section_id']=='s' and first['visual_assets'][0]['asset_id']=='img'
    assert 'image_path' not in first['visual_assets'][0]
    assert restore(first,cache)==a+b
    second=projector.project(payload('[2]',b+c))['result']['evidence'][0]
    assert second['ref']=='[2]' and any('reuse_text_id' in p for p in second['text_parts'])
    assert restore(second,cache)==b+c
    again=projector.project(raw)['result']['evidence'][0]
    assert again['already_provided'] and 'text_parts' not in again


def test_document_boundaries_and_changed_numbers_are_not_merged():
    p=EvidenceProjection();text='value 123 '+('x'*100)
    p.project(payload('[1]',text))
    for r in (payload('[2]',text,'other'),payload('[3]',text.replace('123','124'))):
        e=p.project(r)['result']['evidence'][0]
        assert all('reuse_text_id' not in part for part in e['text_parts'])


def test_discarded_projection_does_not_create_unseen_references():
    p=EvidenceProjection();trial=deepcopy(p);trial.project(payload('[1]','x'*100))
    e=p.project(payload('[1]','x'*100))['result']['evidence'][0]
    assert e['text_parts'][0]['text']=='x'*100 and not e.get('already_provided')

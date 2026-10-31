"""Verify real feature execution rather than accepting fixed-source replay or static flags."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import full_stack_qa_20261031 as study
import report_full_stack_20261031 as report


def configurations():
    a=dict(llm_model='same',llm_reasoning_effort='high',top_k=8,min_score=.35,
        context_expansion={'context_expansion_enabled':True})
    b={**deepcopy(a),'table_retrieval':{'enabled':True},'rerank':{'enabled':True,'model':'BAAI/bge-reranker-v2-m3'},
        'answer_guidance':{'enabled':True,'version':'answer-completeness-v3'}}
    return dict(control=a,guidance=b)


@pytest.mark.parametrize('change',['model','threshold','missing_feature','baseline_enabled','old_prompt'])
def test_bundle_requires_all_features_and_equal_common_settings(change):
    c=configurations();study.validate_flags(c)
    if change=='model':c['guidance']['llm_model']='different'
    elif change=='threshold':c['control']['min_score']=.1
    elif change=='missing_feature':c['guidance']['rerank']['enabled']=False
    elif change=='baseline_enabled':c['control']['table_retrieval']={'enabled':True}
    else:c['guidance']['answer_guidance']['version']='answer-completeness-v2'
    with pytest.raises(ValueError):study.validate_flags(c)


def response():
    return dict(configuration=configurations()['guidance'],embedding_usage={'total_tokens':1},
        rerank_calls=[{'status':'completed','usage':None}],context_assembly={
            'rerank':{'status':'completed','enabled':True,'selected_chunk_ids':['a']},'table_retrieval':{'version':'table-v1'}},
        retrieval_seed_evidence=[{'chunk_id':'a'}],retrieved_evidence=[{'text':'Actual source'}])


@pytest.mark.parametrize('change',['replay','no_embedding','no_rerank','selection_mismatch','no_table','wrong_flag'])
def test_live_trace_rejects_static_or_bypassed_features(change):
    r=response();assert report.trace(r,'guidance','answered')['rerank_calls']==1
    if change=='replay':r['fixed_evidence_diagnostics']={}
    elif change=='no_embedding':r['embedding_usage']=None
    elif change=='no_rerank':r['rerank_calls']=[]
    elif change=='selection_mismatch':r['context_assembly']['rerank']['selected_chunk_ids']=['other']
    elif change=='no_table':r['context_assembly']['table_retrieval']={}
    else:r['configuration']['answer_guidance']['enabled']=False
    with pytest.raises(ValueError):report.trace(r,'guidance','answered')


def test_report_does_not_accept_fixed_evidence_experiment():
    with pytest.raises(ValueError,match='end-to-end'):
        report.analyze({'controls':{'execution_mode':'fixed_retrieved_evidence'}})

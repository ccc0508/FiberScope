"""Reject contaminated contexts/settings and verify source-only offline audit primitives."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import collect_answer_guidance_20261031 as collect


def settings():
    return dict(llm_provider='deepseek',llm_model='fixed',llm_thinking_enabled=True,llm_reasoning_effort='high',
        embedding_provider='openai',embedding_model='fixed-embedding',embedding_dimensions=1024,
        top_k=8,min_score=.35,context_expansion={'budget':24000},table_retrieval={'enabled':True},
        provider_endpoint_fingerprints={'llm':'same'},prompt_pipeline_sha256='new-code')


@pytest.mark.parametrize('change',['model','high','threshold','extra_flag'])
def test_compare_settings_rejects_hidden_model_or_retrieval_changes(change):
    source=settings();arms={'control':deepcopy(source),'guidance':{**deepcopy(source),'answer_guidance':{'enabled':True}}}
    assert collect.compare_settings(arms,source)['control']==collect.compare_settings(arms,source)['guidance']
    if change=='model':arms['guidance']['llm_model']='different'
    elif change=='high':arms['control']['llm_reasoning_effort']='low'
    elif change=='threshold':arms['guidance']['min_score']=.1
    else:arms['guidance']['rerank']={'enabled':True}
    with pytest.raises(ValueError):collect.compare_settings(arms,source)


def fixed():
    evidence=[dict(ref='[1]',chunk_id='c',text='Original text',page_start=2,page_end=2)]
    fixture=dict(version='answer-guidance-fixed-evidence-v1',task_id='A',question='Q',evidences=evidence,
        documents=[dict(document_id='doc',file_hash='pdf')],source_result_sha256='original',evidence_sha256=collect.canonical_sha(evidence))
    source=dict(question='Q',response=dict(retrieved_evidence=evidence,configuration={'documents':fixture['documents']}))
    return fixture,source


@pytest.mark.parametrize('change',['gold','text','locator','order'])
def test_source_fixture_cannot_hide_answers_or_change_locator_order(change):
    fixture,source=fixed();collect.verify_fixture(fixture,source,'A')
    changed=deepcopy(fixture)
    if change=='gold':changed['reference_answer']='forbidden'
    elif change=='text':changed['evidences'][0]['text']='altered'
    elif change=='locator':changed['evidences'][0]['page_start']=3
    else:changed['evidences'].insert(0,{'ref':'[2]','text':'different source'})
    with pytest.raises(ValueError):collect.verify_fixture(changed,source,'A')


def generated():
    fixture,_=fixed();probe=settings()
    response=dict(status='answered',retrieved_evidence=fixture['evidences'],embedding_usage=None,rerank_calls=[],
        fixed_evidence_diagnostics=dict(evidence_sha256=fixture['evidence_sha256'],generation_input_evidence_sha256=fixture['evidence_sha256'],
            source_result_sha256='original',retrieval_bypassed=True,embedding_calls=0,rerank_calls=0),
        configuration=probe,generation_calls=[dict(model_info=dict(requested_model='fixed',thinking_enabled=True,reasoning_effort='high'))])
    return dict(status='answered',response=response),fixture,probe


@pytest.mark.parametrize('change',['hash','new_query','wire_model','third_attempt'])
def test_actual_generation_inputs_and_wire_settings_are_verified(change):
    result,fixture,probe=generated();collect.verify_result(result,fixture,probe)
    if change=='hash':result['response']['fixed_evidence_diagnostics']['generation_input_evidence_sha256']='wrong'
    elif change=='new_query':result['response']['fixed_evidence_diagnostics']['embedding_calls']=1
    elif change=='wire_model':result['response']['generation_calls'][0]['model_info']['requested_model']='different'
    else:result['response']['generation_calls']*=3
    with pytest.raises(ValueError):collect.verify_result(result,fixture,probe)


def test_unobserved_worker_failure_is_not_fabricated_as_verified_evidence():
    _,fixture,probe=generated()
    with pytest.raises(ValueError,match='auditable'):
        collect.verify_result({'status':'failed','response':None},fixture,probe)

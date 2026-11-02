"""Source-coverage and shared-query accounting must not imply semantic accuracy."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from report_embedding_20261102 import retrieval_diff,summarize_coverage,reference_coverage,runtime,interpret


def response():
    evidence=dict(ref='[1]',filename='paper.pdf',page_start=1,page_end=1,chunk_id='a',text='Original text')
    return dict(retrieved_evidence=[evidence],retrieval_seed_evidence=[dict(chunk_id='a')],
        query_embedding_calls=[dict(latency_ms=30,usage=dict(total_tokens=5)),dict(latency_ms=40,usage=dict(total_tokens=6))],
        query_rewrite_calls=[dict(status='replayed_for_controlled_evaluation',api_calls=0,usage=None)],
        generation_calls=[dict(usage=dict(prompt_tokens=10,completion_tokens=8,total_tokens=18,reasoning_tokens=4))],
        rerank_calls=[dict(usage=None)],
        context_assembly=dict(rerank=dict(candidates=[dict(chunk_id='a'),dict(chunk_id='b')]),
            query_rewrite=dict(status='rewritten',branches=[dict(branch='original',query='Original question'),
                                                          dict(branch='rewritten',query='Rewritten question')])))


def test_query_changes_are_rejected_and_source_order_matters():
    b=response();q=deepcopy(b)
    assert retrieval_diff(b,q)['same_initial_generation_input']
    q['retrieved_evidence'][0]['text']='Different text'
    assert not retrieval_diff(b,q)['same_initial_generation_input']
    q['context_assembly']['query_rewrite']['branches'][1]['query']='Different rewritten question'
    with pytest.raises(ValueError,match='confound'):retrieval_diff(b,q)


def test_unresolved_and_review_required_reference_locations_are_not_scored_zero():
    points=[dict(id='P1',optional=False,capability='text',evidence_ids=['E1','E2','E3'])]
    library=dict(alignment={
        'E1':dict(status='located',spans=[dict(source_id='s',start=0,end=10)]),
        'E2':dict(status='review_required',spans=[dict(source_id='s',start=0,end=10)]),
        'E3':dict(status='unresolved',spans=[])},chunk_spans={'a':[dict(source_id='s',start=0,end=10)],'b':[]})
    checks=reference_coverage(dict(key_points=points),['text'],response(),library)
    summary=summarize_coverage([checks])
    assert summary['exact_reference_occurrences']==1 and summary['excluded_occurrences']==2
    assert summary['stages']['final']==dict(numerator=1,denominator=1,value=1)
    checks[0]['stages']['final']['status']='missing'
    assert summarize_coverage([checks])['stages']['final']['value']==0


def test_shared_rewrite_is_not_counted_as_a_paid_generation_call():
    r=response();rt=runtime([dict(status='answered',end_to_end_ms=1000,response=r)])
    assert rt['cached_rewrite_replays']==1 and rt['rewrite_api_calls_during_answers']==0
    assert rt['question_embedding']['calls']==2 and rt['question_embedding']['known_tokens']['total_tokens']==11
    assert rt['generation']['known_tokens']['total_tokens']==18
    assert rt['median_question_embedding_seconds']==.07
    r['query_rewrite_calls'][0]['api_calls']=1
    with pytest.raises(ValueError,match='replayed'):runtime([dict(status='answered',end_to_end_ms=1000,response=r)])


def test_citation_failure_contribution_is_diagnostic_and_does_not_delete_scores():
    rows=[]
    for tid,b,q,reason in [('PFI2-027',0,1,'citation_validation_failed'),
                          ('PFI2-032',0,5/6,'citation_validation_failed'),
                          ('PFI2-025',1,0,None)]:
        rows.append(dict(task_id=tid,bge=dict(metrics=dict(point_mean=b),answer_runtime=dict(reason_code=reason)),
                         qwen=dict(metrics=dict(point_mean=q))))
    before=deepcopy(rows)
    summary=dict(bge=dict(point_macro_average=1/3,all_five_pass=1),
                 qwen=dict(point_macro_average=11/18,all_five_pass=0))
    note=interpret(rows,[r['task_id'] for r in rows],summary)
    assert rows==before
    assert note['baseline_citation_failure_task_ids']==['PFI2-027','PFI2-032']
    parts=note['point_delta_decomposition']
    assert parts['total_percentage_points']==pytest.approx(100*5/18)
    assert parts['other_questions_percentage_points']==pytest.approx(-100/3)

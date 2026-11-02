"""Manual adjudication cannot drop dimensions, alter sealed answers or hide scope denominators."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from report_answer_models_20261102 import manual_decode, final_review
import judge_qa_eval as judge


def packet():
    targets={
        'point_P1':dict(kind='point',point_id='P1'),
        'boundary':dict(kind='boundary'),'reference_check':dict(kind='reference'),
        'kind_C1':dict(kind='claim_type',claim_id='C1'),
        'support_C1':dict(kind='support',claim_id='C1'),
        'basis_C1':dict(kind='basis',claim_id='C1'),
        'group_C1':dict(kind='group',claim_id='C1'),
        'citation_C1_1':dict(kind='citation',claim_id='C1',ref='[1]'),
        'kind_C2':dict(kind='claim_type',claim_id='C2'),
        'support_C2':dict(kind='support',claim_id='C2'),
        'basis_C2':dict(kind='basis',claim_id='C2'),
        'group_C2':dict(kind='group',claim_id='C2'),
        'citation_C2_1':dict(kind='citation',claim_id='C2',ref='[1]')}
    choices=dict(point_P1='complete',boundary='appropriate',reference_check='sound',
        kind_C1='fact',support_C1='supported',basis_C1='E01',group_C1='complete',citation_C1_1='supported',
        kind_C2='scope',support_C2='supported',basis_C2='CONTEXT',group_C2='missing',citation_C2_1='unsupported')
    saved=dict(targets=targets,questions={k:dict(criteria={v:'fixture'}) for k,v in choices.items()},
        state=dict(candidate=dict(claims=[dict(id='C1',text='A measured result'),dict(id='C2',text='Second paper is absent')]),
            verifiable_passages=dict(E01=dict(text='A measured result'))))
    return saved,choices


def test_manual_review_retains_nonapplicability_without_erasing_fact_scores():
    saved,choices=packet();review=manual_decode(choices,saved,{})
    assert review['key_point_scores']=={'P1':1}
    assert [p['score'] for p in review['citation_assessments']]==[1,None]
    assert [g['coverage'] for g in review['citation_group_assessments']]==['complete',None]
    assert len(review['claim_assessments'])==2
    with pytest.raises(ValueError,match='every decision'):
        manual_decode({k:v for k,v in choices.items() if k!='support_C1'},saved,{})


def test_adjudication_rejects_changed_answer_and_missing_reason():
    saved,choices=packet();raw=manual_decode(choices,saved,{})
    row=dict(result_sha256='answerhash',grader_input_sha256='inputhash',raw_review=raw,saved=saved)
    adj=dict(result_sha256='answerhash',grader_input_sha256='inputhash',raw_review_sha256=judge.sha(raw),
        summary='Checked both claims and source.',evidence_checked=['E01','candidate_context'],changes=[])
    assert final_review(row,adj)['decisions']==choices
    with pytest.raises(ValueError,match='answer changed'):
        final_review(row,{**adj,'result_sha256':'different'})
    with pytest.raises(ValueError,match='rationale'):
        final_review(row,{**adj,'summary':''})

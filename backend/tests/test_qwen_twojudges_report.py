"""Keep matching populations and judge disagreements explicit; never average judges."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from report_qwen_twojudges_20261102 import eligible,changes,disagreements
import qa_system_judge as grading
import judge_qa_eval as judge
import judge_qa_jev as jev
from tests.test_qa_system_benchmark import fixture


def test_paired_population_excludes_missing_or_reference_flagged_questions():
    jev_metrics={'A':dict(reference_concern=False),'B':dict(reference_concern=True),'C':dict(reference_concern=False)}
    luna_metrics={'A':dict(reference_concern=False),'B':dict(reference_concern=False)}
    assert sorted(set(eligible(jev_metrics))&set(eligible(luna_metrics)))==['A']


def test_disagreement_lists_five_decisions_but_not_auxiliary_source_locator_choices():
    a=dict(point_P1='complete',support_C1='supported',citation_C1_1='supported',group_C1='complete',
           boundary='appropriate',basis_C1='E01',kind_C1='fact',reference_check='sound')
    b={**a,'point_P1':'partial','basis_C1':'B001','group_C1':'partial'}
    reviews=dict(jev={'A':dict(decisions=a)},luna={'A':dict(decisions=b)})
    original=deepcopy(reviews)
    diff=disagreements(reviews,['A'])
    assert set(diff['A'])==set(grading.POLICY['dimensions'])
    assert diff['A']['key_points']==[dict(item='point_P1',jev='complete',luna='partial')]
    assert diff['A']['citation_support']==[]
    assert reviews==original
    del b['point_P1']
    with pytest.raises(ValueError,match='same decisions'):disagreements(reviews,['A'])


def test_historical_changes_preserve_scores_and_only_compare_explicitly_matched_ids():
    before=dict(A=dict(point_mean=1,all_five_pass=True),B=dict(point_mean=0,all_five_pass=False))
    after=dict(A=dict(point_mean=.5,all_five_pass=False),B=dict(point_mean=1,all_five_pass=True))
    assert changes(before,after,['A'])==dict(point_wins=[],point_losses=['A'],joint_wins=[],joint_losses=['A'])
    assert before['A']['point_mean']==1 and after['A']['point_mean']==.5


def test_both_judges_receive_identical_scientific_state_with_no_failure_draft():
    state,questions,_=fixture()
    # Diagnostics remain in worker results; only imported final candidate is used.
    assert 'citation_validation' not in judge.encode(state)
    luna=judge.Config('https://luna.invalid/v1','openai/gpt-6-luna','unused-test-key')
    other=jev.Config('https://jev.invalid/api','typesafe/jev-1.14','unused-test-key')
    left=grading.request_for('luna',luna,state,questions)
    right=grading.request_for('jev',other,state,questions)
    user=judge.strict_json(left['messages'][1]['content'])
    assert user['state']==right['state'] and user['questions']==right['questions']
    assert left['model']!=right['model'] and 'unused-test-key' not in judge.encode(left)

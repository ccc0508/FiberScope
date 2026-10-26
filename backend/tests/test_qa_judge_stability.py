"""Synthetic-only tests for paired judge repeatability and independent-context auditing."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import compare_qa_judges as comparison
import judge_qa_eval as judge
import aggregate_qa_judges as aggregation
from .test_qa_judge import run_dir,config,make_valid_review,api_response


def synthetic_rounds(vectors=None,strict=None):
    vectors=vectors or [[1,1],[1,1],[1,1]]
    strict=strict or [True,True,True]
    cases={'Q1':{'id':'Q1','question':'Synthetic fixed answer question','key_points':[
        {'id':'P1','optional':False,'capability':'text'},
        {'id':'P2','optional':False,'capability':'text'}]}}
    tasks=[{'id':'Q1','case_id':'Q1','capabilities':['text']}]
    rounds=[]
    for i,values in enumerate(vectors):
        scores=dict(zip(['P1','P2'],values))
        review=dict(task_id='Q1',key_point_scores=scores,answerability_score=2,
                    claim_assessments=[{'id':'C1','support':'supported','claim_type':'fact'}],
                    citation_assessments=[{'claim_id':'C1','ref':'[1]','score':1}],reference_concerns=[])
        row=dict(task_id='Q1',point_mean=sum(values)/2,strict_pass=strict[i],
                 critical_errors=[] if strict[i] else ['Synthetic critical error'])
        rounds.append(dict(name='round-'+str(i+1),reviews=[review],summary={'rows':[row]},api='responses',
                           initial={'Q1':{'raw_response':api_response({'key_point_scores':scores})}}))
    return cases,tasks,rounds


def test_quadratic_kappa_handles_perfect_opposite_and_degenerate_agreement():
    assert comparison.quadratic_kappa([0,.5,1],[0,.5,1])==1
    assert comparison.quadratic_kappa([0,.5,1],[1,.5,0])==pytest.approx(-1)
    assert comparison.quadratic_kappa([1,1],[1,1]) is None
    assert comparison.quadratic_kappa([],[]) is None


def test_question_means_are_continuous_and_not_forced_into_ordinal_kappa():
    result=comparison.pair_numbers({'Q':2/3},{'Q':1},ordinal=False)
    assert result['mean_absolute_difference']==pytest.approx(1/3)
    assert result['weighted_kappa_quadratic'] is None


def test_equal_point_scores_do_not_hide_strict_or_critical_decision_flips():
    cases,tasks,rounds=synthetic_rounds(strict=[True,False,True])
    result=comparison.analyze_rounds(cases,tasks,rounds)
    assert result['overall']['all_rounds_identical_points']['value']==1
    assert result['overall']['strict_pass_flip_tasks']==['Q1']
    assert result['overall']['critical_presence_flip_tasks']==['Q1']
    assert result['pairs'][0]['required_points']['exact_agreement']['value']==1
    assert result['pairs'][0]['strict_pass_agreement']['value']==0


def test_missing_initial_response_is_unknown_and_not_zero():
    cases,tasks,rounds=synthetic_rounds()
    rounds[1]['initial']['Q1']={'status':'api_failed'}
    result=comparison.analyze_rounds(cases,tasks,rounds)
    assert result['pairs'][0]['initial_numeric_points']['exact_agreement']['denominator']==0
    assert result['raw_initial']['common_complete_task_ids']==[]
    assert result['raw_initial']['aligned_initial_macro_averages']==[None,None,None]


def test_changed_point_pattern_is_detected_even_when_question_mean_matches():
    cases,tasks,rounds=synthetic_rounds(vectors=[[1,.5],[.5,1],[1,.5]])
    result=comparison.analyze_rounds(cases,tasks,rounds)
    assert result['questions'][0]['score_range']==0
    assert result['questions'][0]['point_pattern_changed'] is True
    assert result['overall']['all_rounds_identical_points']['value']==0


@pytest.fixture
def audited_study(run_dir,tmp_path):
    review_dirs=[];initials=[]
    for i in [1,2,3]:
        initial=tmp_path/f'initial-{i}';initials.append(initial)
        make_valid_review(run_dir,initial)
        final=tmp_path/f'round-{i}'
        aggregation.aggregate(run_dir,[initial],final)
        review_dirs.append(final)
    tid='PFI2-033-clean'
    study=dict(source_run_sha256=judge.digest(run_dir/'run.json'),
                source_answer_sha256={tid:judge.digest(run_dir/'results'/(tid+'.json'))},
                stateless=True,previous_scores_supplied=False,previous_response_id_used=False,conversation_id_used=False,
                reference_aggregate_sha256=judge.digest(review_dirs[0]/'aggregate-run.json'),
                reference_reviews_sha256=judge.digest(review_dirs[0]/'reviews.jsonl'),
                reference_summary_sha256=judge.digest(review_dirs[0]/'summary.json'),
                reference_initial_record_sha256={tid:judge.digest(initials[0]/'tasks'/(tid+'.json'))},
                initial_request_sha256={tid:judge.read_json(initials[0]/'tasks'/(tid+'.json'))['request_sha256']},
                prompt_sha256=judge.hashlib.sha256(judge.prompt.SYSTEM.encode()).hexdigest(),
                judge=config().public(),additional_initial_rounds=[p.name for p in initials[1:]])
    return study,run_dir,review_dirs


def test_reused_provider_response_id_is_reported_even_for_stateless_requests(audited_study):
    study,source,dirs=audited_study
    result=comparison.audit_study(study,source,dirs)
    assert result['independence_audit']['stateless'] is True
    assert len(result['independence_audit']['reused_response_ids'])==2


def test_conversational_context_or_earlier_scores_prevent_independence_claim(audited_study):
    study,source,dirs=audited_study
    study=deepcopy(study);study['previous_response_id_used']=True
    with pytest.raises(ValueError,match='independent stateless'):
        comparison.audit_study(study,source,dirs)


def test_changed_fixed_answer_is_rejected_instead_of_being_compared(audited_study):
    study,source,dirs=audited_study
    path=source/'results/PFI2-033-clean.json'
    data=judge.read_json(path);data['response']['answer']='Changed answer, no longer fixed'
    path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='checksum|candidate answer changed'):
        comparison.audit_study(study,source,dirs)


def test_changed_initial_prompt_hash_prevents_a_stability_comparison(audited_study):
    study,source,dirs=audited_study
    path=source.parent/'initial-2/tasks/PFI2-033-clean.json'
    data=judge.read_json(path);data['request_sha256']='0'*64
    path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='Initial rating context changed'):
        comparison.audit_study(study,source,dirs)


@pytest.mark.parametrize('allow_incomplete',[False,True])
def test_changed_final_grade_cannot_disagree_with_the_original_api_output(audited_study,allow_incomplete):
    study,source,dirs=audited_study
    path=dirs[1]/'reviews.jsonl'
    rows=judge.read_jsonl(path);rows[0]['point_notes']['P1']='Tampered explanation'
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    with pytest.raises(ValueError,match='Published grades differ'):
        comparison.audit_study(study,source,dirs,allow_incomplete=allow_incomplete)


def test_missing_grade_blocks_full_comparison_but_explicit_subset_is_paired():
    cases,tasks,rounds=synthetic_rounds()
    second={'id':'Q2','case_id':'Q2','capabilities':['text']};tasks.append(second)
    for i,item in enumerate(rounds):
        if i==1:continue
        row=deepcopy(item['summary']['rows'][0]);row['task_id']='Q2';item['summary']['rows'].append(row)
        review=deepcopy(item['reviews'][0]);review['task_id']='Q2';item['reviews'].append(review)
    with pytest.raises(ValueError,match='incomplete'):
        comparison.select_comparable_tasks(tasks,rounds)
    selected,filtered,coverage=comparison.select_comparable_tasks(tasks,rounds,allow_incomplete=True)
    assert [t['id'] for t in selected]==['Q1']
    assert coverage['planned_tasks']==2 and coverage['common_validated_tasks']==1
    assert coverage['excluded_task_ids']==['Q2'] and coverage['full_comparison'] is False
    assert [len(item['reviews']) for item in filtered]==[1,1,1]
    assert [len(item['summary']['rows']) for item in filtered]==[1,1,1]


def test_disputed_reference_is_excluded_from_all_rounds_in_subset_mode():
    cases,tasks,rounds=synthetic_rounds()
    rounds[1]['reviews'][0]['reference_concerns']=['Synthetic disputed reference']
    with pytest.raises(ValueError,match='incomplete'):
        comparison.select_comparable_tasks(tasks,rounds)
    with pytest.raises(ValueError,match='No common validated'):
        comparison.select_comparable_tasks(tasks,rounds,allow_incomplete=True)


def test_subset_option_keeps_full_coverage_when_all_api_outputs_validate(audited_study):
    study,source,dirs=audited_study
    result=comparison.audit_study(study,source,dirs,allow_incomplete=True)
    assert result['coverage']['full_comparison'] is True
    assert result['coverage']['common_validated_tasks']==1
    assert result['coverage']['excluded_task_ids']==[]

"""One-round comparison audits; all labels and upstream HTTP responses are synthetic."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import compare_qa_dual as dual
import judge_qa_eval as judge
import qa_scoring_policy as policy
from .test_qa_jev_comparison import saved_rounds
from .test_qa_judge import run_dir


@pytest.fixture
def one_round(saved_rounds,tmp_path):
    source,_,native,gpt=saved_rounds
    nc=judge.read_json(native[0]/'jev-run.json')['contract']
    aggregate=judge.read_json(gpt[0]/'aggregate-run.json')['contract']
    initial=source.parent/aggregate['component_metadata'][0]['name']
    gc=judge.read_json(initial/'judge-run.json')['contract']
    study=tmp_path/'dual-study';study.mkdir()
    judge.write(study/'study.json',dict(scoring_policy_version=policy.VERSION,scoring_policy_sha256=policy.SHA256,
                source_run_sha256=nc['source_run_sha256'],source_answer_sha256=nc['source_result_hashes'],
                stateless=True,previous_scores_supplied=False,previous_conversation_supplied=False,
                judge_configs={'gpt':gc['judge'],'jev':nc['judge']},harness_files=nc['harness_files'],
                request_sha256={'gpt':{p.stem:judge.read_json(p)['request_sha256'] for p in (initial/'tasks').glob('*.json')},
                                'jev':nc['request_sha256']},initial_directories={'gpt':initial.name,'jev':native[0].name}))
    return source,study,gpt[0],native[0]


def test_one_round_is_not_faked_as_three_and_inputs_remain_unchanged(one_round,tmp_path):
    paths=[p for directory in one_round for p in directory.rglob('*.json')]
    before={p:judge.digest(p) for p in paths}
    result=dual.analyze(*one_round,tmp_path/'comparison')
    assert result['complete'] and result['common_valid_tasks']==1 and result['rounds_per_judge']==1
    assert result['disagreement_task_ids']==[] and result['new_analysis_api_calls']==0
    assert result['agreement_sample']['task_ids']==['PFI2-033-clean']
    assert all(judge.digest(p)==value for p,value in before.items())


@pytest.mark.parametrize('field',['scoring_policy_sha256','previous_scores_supplied'])
def test_changed_policy_or_exposed_prior_scores_block_comparison(one_round,tmp_path,field):
    study=one_round[1]/'study.json';data=judge.read_json(study)
    data[field]='changed' if field.endswith('sha256') else True;judge.write(study,data)
    with pytest.raises(ValueError,match='policy changed|Independent judge context'):
        dual.analyze(*one_round,tmp_path/'invalid')


def test_frozen_initial_request_cannot_be_changed(one_round,tmp_path):
    study=one_round[1]/'study.json';data=judge.read_json(study)
    data['request_sha256']['gpt']['PFI2-033-clean']='changed';judge.write(study,data)
    with pytest.raises(ValueError,match='initial request differs'):
        dual.analyze(*one_round,tmp_path/'changed-request')


def test_agreement_sampling_is_deterministic_and_not_input_order_dependent():
    ids=['Q1','Q2','Q3','Q4','Q5','Q6']
    assert dual.agreement_sample(ids,'frozen-seed')==dual.agreement_sample(list(reversed(ids)),'frozen-seed')
    assert len(dual.agreement_sample(ids,'frozen-seed'))==5

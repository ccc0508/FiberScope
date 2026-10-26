"""No-network paired audits, including original invalid responses and source-integrity gates."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import httpx
import pytest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import compare_qa_jev as comparison
import judge_qa_eval as judge
import judge_qa_jev as jev
import aggregate_qa_judges as aggregation
from .test_qa_judge import run_dir,make_valid_review
from .test_qa_jev import config,response


@pytest.fixture
def saved_rounds(run_dir,tmp_path):
    native=[];gpt=[]
    for n in [1,2,3]:
        directory=tmp_path/f'jev-round-{n}';native.append(directory)
        def handler(request):return httpx.Response(200,json=response(request))
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:jev.run(run_dir,directory,config(),client=client)
        initial=tmp_path/f'gpt-initial-{n}';make_valid_review(run_dir,initial)
        final=tmp_path/f'gpt-round-{n}';aggregation.aggregate(run_dir,[initial],final);gpt.append(final)
    contract=judge.read_json(native[0]/'jev-run.json')['contract']
    study=tmp_path/'study';study.mkdir()
    judge.write(study/'study.json',dict(stateless=True,previous_scores_supplied=False,conversation_identifiers_used=False,
                round_names=[p.name for p in native],source_run_sha256=contract['source_run_sha256'],
                source_answer_sha256=contract['source_result_hashes'],request_sha256=contract['request_sha256'],
                judge=contract['judge'],harness_files=contract['harness_files']))
    return run_dir,study,native,gpt


def test_offline_audit_preserves_raw_scores_and_reports_reused_ids(saved_rounds,tmp_path):
    source,study,native,gpt=saved_rounds
    before={str(p):judge.digest(p) for d in native for p in (d/'tasks').glob('*.json')}
    result=comparison.analyze(source,study,native,gpt,tmp_path/'analysis')
    assert result['canonical_valid_tasks']==[1,1,1]
    assert result['all_six_common_tasks']==1 and result['new_analysis_api_calls']==0
    assert result['reported_jev_cost_usd']=='0.0000126'
    assert result['independent_context']['reused_response_ids']==['synthetic-native-response']
    assert all(judge.digest(Path(p))==h for p,h in before.items())
    assert all(p['required_points']['exact_agreement']['value']==1 for p in result['within_jev'])


def test_mutated_original_native_response_cannot_receive_a_new_score(saved_rounds,tmp_path):
    source,study,native,gpt=saved_rounds
    path=native[1]/'tasks/PFI2-033-clean.json';record=judge.read_json(path)
    record['raw_response']['answers']['point_P1']['choice']='missing';judge.write(path,record)
    with pytest.raises(ValueError,match='API response changed'):
        comparison.analyze(source,study,native,gpt,tmp_path/'tampered-analysis')


def test_mutated_request_is_rejected_even_when_response_is_unchanged(saved_rounds,tmp_path):
    source,study,native,gpt=saved_rounds
    path=native[1]/'requests/PFI2-033-clean.json';request=judge.read_json(path)
    request['state']['candidate']['answer']='Changed after execution';judge.write(path,request)
    with pytest.raises(ValueError,match='request differs'):
        comparison.analyze(source,study,native,gpt,tmp_path/'tampered-request')


def test_invalid_auxiliary_response_can_be_read_without_replaying_or_rewriting_it(saved_rounds,tmp_path):
    source,study,native,gpt=saved_rounds
    path=native[1]/'tasks/PFI2-033-clean.json';record=judge.read_json(path)
    locator=record['raw_response']['answers']['basis_C1'];locator['probabilities']={k:0. for k in locator['probabilities']}
    locator['probabilities'].update(B001=.43,B002=.44,NONE=.13)
    record['response_sha256']=judge.sha(record['raw_response']);record['status']='invalid_response';record.pop('review')
    judge.write(path,record);before=judge.digest(path)
    result=comparison.analyze(source,study,native,gpt,tmp_path/'compatible')
    assert result['canonical_valid_tasks']==[1,1,1] and judge.digest(path)==before
    assert result['jev_rounds'][1]['original_statuses']=={'invalid_response':1}
    assert result['jev_rounds'][1]['diagnostics']['PFI2-033-clean'][0]['kind']=='auxiliary_locator_argmax_mismatch'
    restored=judge.read_jsonl(tmp_path/'compatible/jev-round-2-reviews.jsonl')[0]
    assert restored['claim_assessments'][0]['source_locator']=='B001'


def test_unknown_failure_cost_is_not_reported_as_known_free_request():
    result=comparison.accounting([dict(task_id='Q',api_calls=1,status='api_failed',usage=None,duration_ms=120000)])
    assert result['cost_unknown_calls']==1 and result['usage_unknown_calls']==1
    assert result['known_tokens']['total_tokens']==0
    assert result['actual_invoice_cost'] is None


def test_compatibility_mode_keeps_invalid_core_probability_distributions_rejected(saved_rounds,tmp_path):
    source,study,native,gpt=saved_rounds
    path=native[1]/'tasks/PFI2-033-clean.json';record=judge.read_json(path)
    record['raw_response']['answers']['point_P1']['probabilities']={'missing':0.,'partial':0.,'complete':.4}
    record['response_sha256']=judge.sha(record['raw_response']);record['status']='invalid_response';record.pop('review')
    judge.write(path,record)
    with pytest.raises(ValueError,match='No common Jev grades'):
        comparison.analyze(source,study,native,gpt,tmp_path/'no-silent-relaxation')

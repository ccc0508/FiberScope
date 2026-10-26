"""Synthetic native Decisions API tests; no live model calls or human-authored semantic grades."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import httpx
import pytest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import judge_qa_eval as judge
import judge_qa_jev as jev
import qa_jev_prompt as prompt
from .test_qa_judge import run_dir


def config():return jev.Config('https://openrouter.ai/api','typesafe/jev-1.14','SYNTHETIC_JEV_KEY')


def response(request):
    body=json.loads(request.content);answers={}
    for key,question in body['questions'].items():
        if key.startswith('point_'):selected='complete'
        elif key.startswith('kind_'):selected='fact'
        elif key.startswith('support_'):selected='supported'
        elif key.startswith('basis_'):selected='B001'
        else:selected='supported'
        answers[key]=dict(type='choice',choice=selected,confidence=1.,
                          probabilities={label:float(label==selected) for label in question['criteria']})
    return dict(id='synthetic-native-response',model='typesafe/jev-1.14-20261014',provider='TypeSafe',answers=answers,
                usage=dict(input_tokens=100,output_tokens=20,cost=.0000042))


def test_native_endpoint_independent_input_and_resume_without_duplicate_cost(run_dir,tmp_path):
    payloads=[]
    def handle(request):
        assert str(request.url)=='https://openrouter.ai/api/alpha/decisions'
        payload=json.loads(request.content);payloads.append(payload)
        assert set(payload)=={'model','state','questions','provider'}
        assert payload['provider']=={'allow_fallbacks':False}
        assert 'OLD_REVIEW_SCORE_CANARY' not in request.content.decode()
        assert 'ANSWER_MODEL_MUST_BE_HIDDEN' not in request.content.decode()
        return httpx.Response(200,json=response(request))
    target=tmp_path/'jev'
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        first=jev.run(run_dir,target,config(),client=client)
        second=jev.run(run_dir,target,config(),client=client)
    assert len(payloads)==1 and first['valid_reviews']==1 and first['summary_written']
    assert second['api_calls_this_invocation']==0 and second['application_calls']==1
    assert second['reported_cost_usd']=='0.0000042'
    assert first['full_strict_pass'] is None
    record=judge.read_json(target/'tasks/PFI2-033-clean.json')
    assert record['review']['claim_assessments'][0]['basis'][0]['quote']==payloads[0]['state']['verifiable_passages']['B001']['quote']
    assert not any(config().api_key in p.read_text(encoding='utf-8') for p in target.rglob('*.json'))


@pytest.mark.parametrize('status',[401,402,403,429,503])
def test_failure_is_preserved_unknown_cost_and_never_retried_implicitly(run_dir,tmp_path,status):
    calls=[]
    def failed(request):calls.append(1);return httpx.Response(status,text='synthetic error '+config().api_key)
    with httpx.Client(transport=httpx.MockTransport(failed)) as client:
        first=jev.run(run_dir,tmp_path/'failed',config(),client=client)
        second=jev.run(run_dir,tmp_path/'failed',config(),client=client)
    assert len(calls)==1 and first['valid_reviews']==0 and second['api_calls_this_invocation']==0
    assert first['cost_unknown_calls']==1 and first['usage_unknown_calls']==1
    assert not first['summary_written']
    assert not any(config().api_key in p.read_text(encoding='utf-8') for p in (tmp_path/'failed').rglob('*.json'))


def test_bad_probability_map_is_rejected_with_usage_retained(run_dir,tmp_path):
    def bad(request):
        body=response(request);key=next(iter(body['answers']));body['answers'][key]['probabilities']={'invented':1}
        return httpx.Response(200,json=body)
    with httpx.Client(transport=httpx.MockTransport(bad)) as client:
        result=jev.run(run_dir,tmp_path/'bad-probabilities',config(),client=client)
    assert result['statuses']=={'invalid_response':1}
    assert result['known_tokens']['total_tokens']==120 and result['reported_cost_usd']=='0.0000042'


def test_scope_citation_is_excluded_by_code_but_native_decision_is_preserved(run_dir,tmp_path):
    def scope(request):
        body=response(request);kind=body['answers']['kind_C1']
        kind.update(choice='scope',probabilities={'fact':0.,'scope':1.})
        locator=body['answers']['basis_C1'];locator['choice']='FULL_TEXT_SCOPE'
        locator['probabilities']={k:float(k=='FULL_TEXT_SCOPE') for k in locator['probabilities']}
        return httpx.Response(200,json=body)
    target=tmp_path/'scope'
    with httpx.Client(transport=httpx.MockTransport(scope)) as client:jev.run(run_dir,target,config(),client=client)
    review=judge.read_json(target/'tasks/PFI2-033-clean.json')['review']
    assert review['citation_assessments'][0]['raw_score']==1 and review['citation_assessments'][0]['score'] is None
    assert review['claim_assessments'][0]['evidence_location_status']=='fulltext_scope_selected'


def test_none_evidence_is_unknown_location_without_fabricating_a_quote(run_dir,tmp_path):
    def unlocated(request):
        body=response(request);entry=body['answers']['basis_C1'];entry['choice']='NONE'
        entry['probabilities']={key:float(key=='NONE') for key in entry['probabilities']}
        return httpx.Response(200,json=body)
    with httpx.Client(transport=httpx.MockTransport(unlocated)) as client:
        result=jev.run(run_dir,tmp_path/'none',config(),client=client)
    review=judge.read_json(tmp_path/'none/tasks/PFI2-033-clean.json')['review']
    assert result['valid_reviews']==1 and result['all_evidence_located_tasks']==0
    assert review['claim_assessments'][0]['basis']==[]
    assert review['claim_assessments'][0]['support']=='supported'


def test_changed_saved_decision_and_source_answer_are_rejected(run_dir,tmp_path):
    target=tmp_path/'tampered'
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=response(request)))) as client:
        jev.run(run_dir,target,config(),client=client)
    path=target/'tasks/PFI2-033-clean.json';record=judge.read_json(path)
    record['review']['key_point_scores']['P1']=0;judge.write(path,record)
    with pytest.raises(ValueError,match='decisions changed'):jev.run(run_dir,target,config())


def test_three_rounds_have_identical_payloads_and_distinct_output_directories(run_dir,tmp_path):
    payloads=[]
    def handle(request):payloads.append(json.loads(request.content));return httpx.Response(200,json=response(request))
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        for n in [1,2,3]:jev.run(run_dir,tmp_path/f'round-{n}',config(),client=client)
    assert len(payloads)==3 and payloads[0]==payloads[1]==payloads[2]


def test_pending_request_is_not_paid_twice(run_dir,tmp_path):
    target=tmp_path/'pending'
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json=response(request)))) as client:
        jev.run(run_dir,target,config(),client=client)
    path=target/'tasks/PFI2-033-clean.json';record=judge.read_json(path);record['status']='pending';judge.write(path,record)
    with httpx.Client(transport=httpx.MockTransport(lambda request:pytest.fail('No request may be replayed'))) as client:
        result=jev.run(run_dir,target,config(),client=client)
    assert result['api_calls_this_invocation']==0 and result['statuses']=={'pending':1}


def test_configuration_does_not_inherit_gpt_or_answering_key(tmp_path,monkeypatch):
    path=tmp_path/'private.env';path.write_text('QA_JEV_API_KEY=\n')
    monkeypatch.setenv('OPENROUTER_API_KEY','OTHER_SERVICE_KEY')
    monkeypatch.setenv('QA_JUDGE_API_KEY','OTHER_JUDGE_KEY')
    with pytest.raises(ValueError,match='private OpenRouter key'):jev.load_config(path)


def test_unexpected_model_is_rejected(run_dir,tmp_path):
    def wrong(request):
        body=response(request);body['model']='typesafe/jev-1.140';return httpx.Response(200,json=body)
    with httpx.Client(transport=httpx.MockTransport(wrong)) as client:
        result=jev.run(run_dir,tmp_path/'wrong-model',config(),client=client)
    assert result['statuses']=={'invalid_response':1}

"""Credential isolation and OpenRouter protocol checks; no live model calls."""
from pathlib import Path
import sys

import httpx
import pytest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
import judge_qa_eval as judge
import judge_qa_luna as luna
from .test_qa_judge import run_dir,scorecard,api_response


def config():
    return judge.Config(luna.BASE_URL,luna.MODEL,'SYNTHETIC_LUNA_KEY','chat_completions')


def test_dry_run_prepares_same_v3_answer_without_key_or_model_calls(run_dir,tmp_path):
    env=tmp_path/'luna.env';env.write_text('QA_LUNA_API_KEY=\n')
    result=luna.prepare(run_dir,luna.load_config(env,require_key=False))
    assert result['prepared_tasks']==1 and result['model_calls']==0
    assert result['credential_configured'] is False and result['paid_validation_performed'] is False
    assert result['requested_model']=='openai/gpt-6-luna'


def test_luna_never_inherits_gpt_jev_or_generic_openrouter_key(tmp_path,monkeypatch):
    env=tmp_path/'luna.env';env.write_text('QA_LUNA_API_KEY=\n')
    for name in ('QA_JUDGE_API_KEY','QA_JEV_API_KEY','OPENROUTER_API_KEY'):
        monkeypatch.setenv(name,'OTHER_KEY_MUST_NOT_BE_USED')
    monkeypatch.delenv('QA_LUNA_API_KEY',raising=False)
    with pytest.raises(ValueError,match='QA_LUNA_API_KEY'):
        luna.load_config(env)


@pytest.mark.parametrize('line',['QA_LUNA_MODEL=openai/gpt-6-luna-pro','QA_LUNA_BASE_URL=https://wrong.invalid/api/v1',
                                 'QA_LUNA_API=responses','QA_LUNA_TIMEOUT_SECONDS=nan'])
def test_wrong_model_endpoint_or_request_settings_are_rejected(tmp_path,line):
    env=tmp_path/'luna.env';env.write_text('QA_LUNA_API_KEY=SYNTHETIC_LUNA_KEY\n'+line+'\n')
    with pytest.raises(ValueError):luna.load_config(env)


def test_openrouter_chat_request_keeps_v3_blinding_and_records_reported_charge(run_dir,tmp_path):
    calls=[]
    def handler(request):
        calls.append(request)
        assert str(request.url)==luna.BASE_URL+'/chat/completions'
        body=judge.strict_json(request.content.decode())
        assert body['model']==luna.MODEL and body['response_format']=={'type':'json_object'}
        assert [m['role'] for m in body['messages']]==['system','user']
        assert not {'models','session_id','conversation','previous_response_id'} & set(body)
        packet=judge.strict_json(body['messages'][1]['content'])
        response=api_response(scorecard(packet),mode='chat_completions')
        response.update(model=luna.MODEL,usage=dict(prompt_tokens=100,completion_tokens=40,total_tokens=140,cost=.00003))
        return httpx.Response(200,json=response)
    out=tmp_path/'luna-only'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first=luna.run(run_dir,out,config(),client=client)
        second=luna.run(run_dir,out,config(),client=client)
    assert len(calls)==1 and first['completed']==1 and second['api_calls_this_invocation']==0
    costs=judge.read_json(out/'openrouter-costs.json')
    assert costs['reported_cost_usd']=='0.00003' and costs['cost_unknown_calls']==0
    assert 'SYNTHETIC_LUNA_KEY' not in config().public().values()
    assert not any(config().api_key in p.read_text(encoding='utf-8') for p in out.rglob('*.json'))


def test_missing_fee_is_explicitly_unknown_including_network_failures(tmp_path):
    (tmp_path/'tasks').mkdir()
    judge.write(tmp_path/'tasks/failure.json',dict(task_id='Q',status='api_failed',api_calls=1,usage=None))
    result=luna.cost_summary(tmp_path)
    assert result['cost_unknown_calls']==1 and result['cost_known_calls']==0 and result['actual_invoice_cost'] is None

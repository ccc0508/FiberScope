import json
import httpx
import pytest

from literature_rag.adapters.providers.alternate_rerank import NativeReranker,build_reranker
from literature_rag.config import Settings
from literature_rag.domain.errors import ProviderError


def test_dashscope_full_text_complete_indexes_default_instruction():
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json=dict(output=dict(results=[dict(index=1,relevance_score=.8),dict(index=0,relevance_score=.1)]),usage=dict(total_tokens=50)))
    r=NativeReranker('qwen3.7-text-rerank','private-token','https://example.invalid/api/v1',provider='dashscope',client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert r.rerank('Q',['A'*12000,'B'])==[.1,.8]
    assert requests[0]['input']['documents']==['A'*12000,'B']
    assert 'instruct' not in requests[0]['parameters']
    assert r.last_call['api_calls']==1 and r.last_call['usage']['total_tokens']==50


def test_jev_independent_calls_order_and_accounting():
    requests=[]
    def handler(request):
        payload=json.loads(request.content);requests.append(payload)
        return httpx.Response(200,json=dict(model='typesafe/jev-1.14-20261014',provider='TypeSafe',answers=dict(relevance=dict(type='score',score=3 if payload['state']['passage']=='A' else 1.5)),usage=dict(input_tokens=20,output_tokens=1,cost=.001)))
    r=NativeReranker('typesafe/jev-1.14','private-token','https://example.invalid/api',provider='jev',client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert r.rerank('Q',['A','B'])==[1,.5]
    assert {tuple(p['state']) for p in requests}=={('query','passage')}
    assert r.last_call['api_calls']==2 and r.last_call['monetary_cost']==.002
    assert 'private-token' not in json.dumps(r.last_call)


@pytest.mark.parametrize('status',[402,503])
def test_failure_retains_trace_without_vector_or_model_fallback(status):
    count=[]
    def handler(request):
        count.append(1);return httpx.Response(status,text='private-token')
    r=NativeReranker('qwen3.7-text-rerank','private-token','https://example.invalid',provider='dashscope',client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError):r.rerank('Q',['A'])
    assert len(count)==1 and r.last_call['status']=='failed'


def test_jev_incomplete_scores_fail_whole_ranking():
    def handler(request):
        return httpx.Response(200,json=dict(model='typesafe/jev-1.14',provider='TypeSafe',answers=dict(relevance=dict(type='score',score=float('nan')))))
    # Raw invalid JSON must fail too, without escaping provider detail.
    client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,text='{"answers":{}}')))
    r=NativeReranker('typesafe/jev-1.14','private-token','https://example.invalid',provider='jev',client=client)
    with pytest.raises(ProviderError):r.rerank('Q',['A'])
    assert r.last_call['api_calls']==1


def test_factory_keeps_siliconflow_default():
    s=Settings(_env_file=None,rerank_enabled=True,rerank_api_key='private-token',rerank_base_url='https://example.invalid')
    assert type(build_reranker(s)).__name__=='SiliconFlowReranker'

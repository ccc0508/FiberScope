"""Rerank provider contract, source identity, bounded requests and failure accounting."""
from dataclasses import replace
from math import nan,inf
from types import SimpleNamespace as NS
import json

import httpx
import pytest

from literature_rag.adapters.providers.rerank import SiliconFlowReranker
from literature_rag.application.retrieve import RetrievalService
from literature_rag.config import Settings
from literature_rag.diagnostics import configuration_snapshot
from literature_rag.domain.errors import ProviderError,ProviderResponseError
from literature_rag.domain.models import Chunk,VectorMatch
from tests.literature_fakes import InMemoryMetadataStore,SpyEmbedder


def provider(handler):
    client=httpx.Client(transport=httpx.MockTransport(handler))
    return SiliconFlowReranker('BAAI/bge-reranker-v2-m3','private-test-token','https://api.example/v1',client=client)


def test_provider_maps_out_of_order_indexes_and_sends_full_source_once():
    requests=[];texts=['<table>'+('x'*9000)+'</table>','Another source']
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json=dict(results=[dict(index=1,relevance_score=.9),dict(index=0,relevance_score=.1)],
            meta={'tokens':{'input_tokens':42,'output_tokens':0}}))
    p=provider(handler)
    assert p.rerank('Question',texts)==[.1,.9]
    payload=json.loads(requests[0].content)
    assert payload['documents']==texts and payload['query']=='Question' and payload['top_n']==2
    assert payload['max_chunks_per_doc']==1024 and payload['overlap_tokens']==80
    assert len(requests)==1 and p.last_call['usage']=={'input_tokens':42,'output_tokens':0}
    assert 'private-test-token' not in json.dumps(p.last_call)


@pytest.mark.parametrize('results',[
    [dict(index=0,relevance_score=.2)],
    [dict(index=0,relevance_score=.2),dict(index=0,relevance_score=.9)],
    [dict(index=True,relevance_score=.2),dict(index=1,relevance_score=.9)],
    [dict(index=0,relevance_score=nan),dict(index=1,relevance_score=.9)],
    [dict(index=0,relevance_score=inf),dict(index=1,relevance_score=.9)],
    [dict(index=0,relevance_score=True),dict(index=1,relevance_score=.9)],
    [dict(index=0,relevance_score=1.1),dict(index=1,relevance_score=.9)],
    [dict(index=0,relevance_score=.2),dict(index=2,relevance_score=.9)],
])
def test_invalid_scores_indexes_or_partial_response_are_rejected(results):
    def handler(request):
        # Raw JSON is intentional: malformed providers may emit nonfinite values.
        return httpx.Response(200,text=json.dumps({'results':results}))
    p=provider(handler)
    with pytest.raises(ProviderResponseError):p.rerank('Question',['One','Two'])
    assert p.last_call['status']=='invalid_response' and p.last_call['api_calls']==1


@pytest.mark.parametrize('status',[401,402,429,503])
def test_http_failures_have_no_retry_or_leaked_provider_error(status):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,text='private-test-token raw private error')
    p=provider(handler)
    with pytest.raises(ProviderError) as error:p.rerank('Question',['One'])
    assert 'private-test-token' not in str(error.value) and len(calls)==1
    assert p.last_call['status']=='request_failed' and p.last_call['usage'] is None


def test_transport_failure_is_counted_and_redacted():
    def handler(request):raise httpx.ReadTimeout('private-test-token')
    p=provider(handler)
    with pytest.raises(ProviderError) as error:p.rerank('Question',['One'])
    assert 'private-test-token' not in str(error.value) and p.last_call['status']=='request_failed'


def service(reranker=None):
    chunk=Chunk('a','doc','paper.pdf',1,1,0,'First original source',5,'fake')
    second=replace(chunk,id='b',chunk_index=1,text='<table>Second original source</table>',kind='table')
    metadata=InMemoryMetadataStore();metadata.chunks={c.id:c for c in [chunk,second]}
    vectors=NS(search=lambda q,k:[VectorMatch('a',.9),VectorMatch('b',.4),VectorMatch('b',.3),VectorMatch('orphan',.99)])
    return RetrievalService(metadata,vectors,SpyEmbedder(),reranker=reranker)


def test_rank_changes_without_overwriting_cosine_or_using_it_as_rerank_threshold():
    calls=[]
    def rank(q,texts):calls.append((q,texts));return [.01,.02]
    s=service(NS(rerank=rank));result=s.retrieve('  Question  ',1,.35)
    assert calls==[('Question',['First original source','<table>Second original source</table>'])]
    assert len(result)==1 and result[0].chunk_id=='b' and result[0].score==.4 and result[0].ref=='[1]'
    assert result[0].text=='<table>Second original source</table>'
    assert s.last_context_diagnostics['rerank']['candidates'][0]['vector_rank']==2


def test_disabled_path_preserves_vector_order_and_diagnostics_shape():
    s=service();result=s.retrieve('Question',1,.35)
    assert result[0].chunk_id=='a' and 'rerank' not in s.last_context_diagnostics


def test_empty_candidates_do_not_call_reranker_and_failure_does_not_fallback():
    calls=[]
    def fail(*args):calls.append(args);raise ProviderError('unavailable')
    s=service(NS(rerank=fail));assert s.retrieve('Question',1,1)==[] and calls==[]
    with pytest.raises(ProviderError):s.retrieve('Question',1,.35)
    assert len(calls)==1 and not s.last_seed_evidences


def test_config_switch_requires_credentials_and_snapshot_contains_no_secret(tmp_path):
    assert Settings(_env_file=None).rerank_enabled is False
    with pytest.raises(ValueError):Settings(_env_file=None,rerank_enabled=True)
    with pytest.raises(ValueError):Settings(_env_file=None,rerank_base_url='https://user:secret@example.com')
    p=tmp_path/'settings.env'
    p.write_text('RAG_RERANK_ENABLED=true\nRAG_RERANK_API_KEY=private-test-token\nRAG_RERANK_BASE_URL=https://api.example/v1\n',encoding='utf-8')
    snapshot=configuration_snapshot(p)
    assert 'private-test-token' not in json.dumps(snapshot)
    assert snapshot['rerank']['retry_count']==0 and snapshot['rerank']['score_threshold'] is None

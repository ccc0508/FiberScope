"""Dual retrieval controls: source identity, fair budget, anchors and observable costs."""
from dataclasses import replace
import json
from types import SimpleNamespace as NS

import httpx
from openai import OpenAI
import pytest

from literature_rag.adapters.providers.query_rewrite import DeepSeekQueryRewriter
from literature_rag.application.query_rewrite import protected_anchors, validate_rewrite
from literature_rag.application.retrieve import RetrievalService
from literature_rag.config import Settings
from literature_rag.diagnostics import combined_usage, configuration_snapshot
from literature_rag.domain.errors import ProviderError, ProviderResponseError
from literature_rag.domain.models import Chunk, VectorMatch
from tests.literature_fakes import InMemoryMetadataStore


def make_service(original, rewritten, rewrite='Rewritten question'):
    metadata = InMemoryMetadataStore()
    for i, cid in enumerate(dict.fromkeys(cid for cid, _ in original + rewritten)):
        metadata.chunks[cid] = Chunk(cid, 'doc', 'paper.pdf', 1, 1, i, 'Source '+cid, 5, 'fake')
    class Embedder:
        def __init__(self): self.calls = []; self.last_usage = None
        def embed_query(self, text):
            self.calls.append(text); self.last_usage = dict(prompt_tokens=len(text), total_tokens=len(text))
            return [len(self.calls)]
    class Vectors:
        def search(self, vector, limit):
            assert limit == 50
            return [VectorMatch(*m) for m in (original if vector == [1] else rewritten)]
    class Rewriter:
        last_call = dict(status='completed', usage=dict(total_tokens=12))
        def rewrite(self, question):
            if isinstance(rewrite, Exception): raise rewrite
            return rewrite
    calls = []
    def rank(question, texts):
        calls.append((question, texts))
        return [.5] * len(texts)
    s = RetrievalService(metadata, Vectors(), Embedder(), reranker=NS(rerank=rank), query_rewriter=Rewriter())
    return s, calls


def test_duplicate_sources_are_reranked_once_using_original_question():
    s, calls = make_service([('a', .7), ('a', .6), ('b', .4)], [('b', .95), ('c', .8), ('a', .5)])
    result = s.retrieve('  Original question  ', 8, .35)
    assert calls[0][0] == 'Original question' and len(calls[0][1]) == 3
    assert len({e.chunk_id for e in result}) == len(result) == 3
    assert s.embedder.calls == ['Original question', 'Rewritten question']
    diag = s.last_query_diagnostics
    assert diag['shared_candidates'] == 2 and diag['unique_candidates'] == 3
    assert diag['rewrite_only_candidate_ids'] == diag['rewrite_only_selected_ids'] == ['c']
    # Shared blocks retain original-branch cosine, not the larger rewrite cosine.
    assert next(e for e in result if e.chunk_id == 'b').score == .4
    assert len(s.last_query_embedding_calls) == 2
    assert combined_usage(s.last_query_embedding_calls)['total_tokens'] == sum(map(len, s.embedder.calls))


def test_rank_fusion_budget_and_threshold_do_not_double_candidate_count():
    s, calls = make_service([(f'c{i:02}', .7) for i in range(50)], [(f'c{i:02}', .8) for i in range(25, 75)])
    result = s.retrieve('Original question', 8, .35)
    assert len(calls[0][1]) == 50 and len(result) == 8
    diag = s.last_query_diagnostics
    assert diag['unique_candidates'] == 75 and diag['shared_candidates'] == 25
    assert diag['candidate_count_after_budget'] == 50
    assert len({e['chunk_id'] for e in diag['fused_candidates']}) == 75
    assert all(e['chunk_id'] in {f'c{i:02}' for i in range(25, 50)} for e in diag['fused_candidates'][:25])


@pytest.mark.parametrize('rewrite,status', [
    ('Original question', 'unchanged'),
    (ProviderError('private error'), 'rewrite_failed_original_only'),
    ('', 'rewrite_failed_original_only'),
])
def test_unchanged_or_failed_rewrite_searches_original_once(rewrite, status):
    s, calls = make_service([('a', .8)], [('b', .9)], rewrite)
    assert [e.chunk_id for e in s.retrieve('Original question', 8, .35)] == ['a']
    assert s.last_query_diagnostics['status'] == status and s.embedder.calls == ['Original question']
    assert len(calls) == 1 and 'private error' not in json.dumps(s.last_query_diagnostics)


def test_dropped_numbers_or_identifiers_fall_back_and_low_scores_stay_filtered():
    question = '针叶木0.919、阔叶木0.925和CI-XI、CI-XA的关系？'
    assert {'0.919', '0.925', 'CI-XI', 'CI-XA'} <= protected_anchors(question)
    s, _ = make_service([('a', .8), ('b', .2)], [('c', .9)], '仅讨论CI-XI和CI-XA')
    assert [e.chunk_id for e in s.retrieve(question, 8, .35)] == ['a']
    assert s.last_query_diagnostics['status'] == 'rewrite_failed_original_only'
    with pytest.raises(ProviderResponseError): validate_rewrite(question, 'x'*1201)


def test_state_resets_between_questions_and_orphans_do_not_use_fused_budget():
    s, _ = make_service([('a', .8), ('missing', .9)], [('b', .8)])
    del s.metadata.chunks['missing']
    first = s.retrieve('Original question', 8, .35)
    assert len(first) == 2 and s.last_query_diagnostics['unique_candidates'] == 2
    s.retrieve('Second question', 8, .35)
    assert len(s.last_query_embedding_calls) == 2 and len(s.last_query_diagnostics['branches']) == 2


def provider(handler):
    client = OpenAI(api_key='private-test-key', base_url='https://example.invalid/v1', max_retries=0,
                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return DeepSeekQueryRewriter('deepseek-flash', 'unused', client=client)


def test_provider_uses_one_bounded_non_thinking_call_and_preserves_usage():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=dict(id='r', model='returned-model', choices=[dict(
            index=0, message=dict(role='assistant', content=json.dumps({'query': '竹浆打浆时间延长后强度和滤水性能的变化'})),
            finish_reason='stop')], usage=dict(prompt_tokens=21, completion_tokens=9, total_tokens=30)))
    p = provider(handler)
    assert p.rewrite('竹浆纸更结实但水下得慢？').startswith('竹浆')
    body = json.loads(requests[0].content)
    assert body['thinking'] == {'type': 'disabled'} and body['temperature'] == 0 and body['max_tokens'] == 768
    assert len(body['messages']) == 2 and len(requests) == 1
    assert p.last_call['usage']['total_tokens'] == 30 and p.last_call['returned_model'] == 'returned-model'
    assert 'private-test-key' not in json.dumps(p.last_call)


@pytest.mark.parametrize('content', ['{"query":"Other question","answer":"invented"}', '{"query":12}', 'not json'])
def test_malformed_response_is_counted_and_rejected(content):
    p = provider(lambda request: httpx.Response(200, json=dict(id='r', model='m', choices=[dict(index=0,
        message=dict(role='assistant', content=content), finish_reason='stop')])))
    with pytest.raises(ProviderResponseError): p.rewrite('Question')
    assert p.last_call['status'] == 'invalid_response' and p.last_call['api_calls'] == 1


def test_failed_request_is_not_retried_or_leaked():
    calls = []
    def handler(request): calls.append(request); return httpx.Response(503, text='private-test-key raw error')
    p = provider(handler)
    with pytest.raises(ProviderError) as error: p.rewrite('Question')
    assert len(calls) == 1 and 'private-test-key' not in str(error.value)
    assert p.last_call['status'] == 'request_failed' and p.last_call['usage'] is None


def test_config_and_unknown_cost_accounting(tmp_path):
    assert not Settings(_env_file=None).query_rewrite_enabled
    with pytest.raises(ValueError): Settings(_env_file=None, query_rewrite_enabled=True)
    path = tmp_path/'config.env'
    path.write_text('RAG_QUERY_REWRITE_ENABLED=true\nRAG_RERANK_ENABLED=true\nRAG_LLM_PROVIDER=deepseek\n'
        'RAG_LLM_MODEL=deepseek-flash\nRAG_LLM_API_KEY=private-test-key\nRAG_RERANK_API_KEY=private-test-key\n'
        'RAG_RERANK_BASE_URL=https://example.invalid/v1\n', encoding='utf-8')
    snap = configuration_snapshot(path)
    assert snap['query_rewrite']['merged_candidate_limit'] == 50 and 'private-test-key' not in json.dumps(snap)
    assert combined_usage([dict(usage={'total_tokens': 10}), dict(usage=None)]) is None

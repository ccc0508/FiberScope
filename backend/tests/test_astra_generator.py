"""Responses model substitution preserves source images and independent retrieval credentials."""
import base64
import json
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from literature_rag.adapters.providers.openai import OpenAIGenerator, _client
from literature_rag.config import Settings
from literature_rag.diagnostics import configuration_snapshot
from tests.test_visual_evidence import fixture, PNG


def test_astra_responses_sends_verified_pixels_high_and_no_storage(tmp_path):
    catalog, es, _ = fixture(tmp_path)
    es, _ = catalog.attach(es[:1], es[:1], 'Figure 1')
    requests = []
    def parse(**body):
        requests.append(body)
        return NS(model='gpt-6-astra', usage=None, output_parsed=dict(
            answer='Source observation [1]', claims=[dict(text='Source observation', citation_refs=['[1]'])]))
    g = OpenAIGenerator('gpt-6-astra', 'PRIVATE', client=NS(responses=NS(parse=parse)),
        reasoning_effort='high', visual_root=tmp_path)
    answer = g.generate('Question', es)
    body = requests[0]
    assert body['model'] == 'gpt-6-astra' and body['store'] is False
    assert body['reasoning'] == {'effort': 'high'} and 'tools' not in body
    content = body['input'][1]['content']
    img = next(b for b in content if b['type'] == 'input_image')
    assert base64.b64decode(img['image_url'].split(',', 1)[1]) == PNG
    assert img['detail'] == 'original' and 'Original PDF' not in answer.answer
    assert any('[1] ORIGINAL PDF IMAGE: Figure 1' in b.get('text', '') for b in content)
    assert g.last_model_info['returned_model'] == 'gpt-6-astra'
    assert g.last_model_info['image_count'] == 1 and 'base64' not in json.dumps(g.last_model_info)


def test_actor_header_is_explicit_and_not_ambient(monkeypatch):
    monkeypatch.setenv('OPENAI_ORG_ID', 'UNRELATED_ORG')
    c = _client('PRIVATE_KEY', 'https://example.invalid/v1', timeout=180,
        actor_authorization='EXPLICIT_ACTOR')
    try:
        assert c._custom_headers == {'x-openai-actor-authorization': 'EXPLICIT_ACTOR'}
        assert c.organization is None and c.project is None and c.timeout == 180
    finally:
        c.close()


def settings(**overrides):
    return Settings(_env_file=None, embedding_provider='dashscope', embedding_model='qwen3-vl-embedding',
        embedding_dimensions=2560, visual_retrieval_enabled=True, context_expansion_enabled=True,
        context_expansion_strategy='body_section', rerank_enabled=True, rerank_base_url='https://example.invalid',
        rerank_api_key='RERANK_PRIVATE', query_rewrite_enabled=True, llm_provider='openai', llm_model='gpt-6-astra',
        llm_api_key='GPT_PRIVATE', **overrides)


def test_gpt_cannot_silently_reuse_answer_credentials_for_deepseek_rewrite():
    with pytest.raises(ValidationError, match='DeepSeek credentials'):
        settings()
    with pytest.raises(ValidationError, match='model, API key and base URL'):
        settings(query_rewrite_model='deepseek-flash')
    s = settings(query_rewrite_model='deepseek-flash', query_rewrite_api_key='REWRITE_PRIVATE',
        query_rewrite_base_url='https://api.deepseek.com')
    assert s.llm_model == 'gpt-6-astra' and s.query_rewrite_model == 'deepseek-flash'


def test_public_snapshot_records_rewrite_model_without_either_secret(tmp_path):
    p = tmp_path/'private.env'
    p.write_text('RAG_LLM_MODEL=gpt-6-astra\nRAG_LLM_API_KEY=GPT_PRIVATE\n'
        'RAG_LLM_ACTOR_AUTHORIZATION=ACTOR_PRIVATE\nRAG_QUERY_REWRITE_ENABLED=true\n'
        'RAG_QUERY_REWRITE_MODEL=deepseek-flash\nRAG_QUERY_REWRITE_API_KEY=REWRITE_PRIVATE\n'
        'RAG_QUERY_REWRITE_BASE_URL=https://api.deepseek.com\nRAG_RERANK_ENABLED=true\n'
        'RAG_RERANK_BASE_URL=https://example.invalid\nRAG_RERANK_API_KEY=RERANK_PRIVATE\n', encoding='utf-8')
    snapshot = configuration_snapshot(p)
    assert snapshot['llm_model'] == 'gpt-6-astra'
    assert snapshot['query_rewrite']['model'] == 'deepseek-flash'
    assert snapshot['generation_runtime']['actor_header_configured'] is True
    assert 'PRIVATE' not in json.dumps(snapshot)

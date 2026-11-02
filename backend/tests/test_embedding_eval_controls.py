"""Embedding comparisons must preserve query rewrites and all non-embedding controls."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from evaluate_embedding_20261102 import comparable_configuration
from qa_embedding_eval_worker import replay_rewriter
from literature_rag.domain.errors import ProviderError


def test_configuration_comparison_excludes_only_embedding_identity_and_endpoint():
    bge=dict(embedding_provider='openai',embedding_model='BAAI/bge-m3',embedding_dimensions=1024,
        embedding_runtime=None,pipeline_source_files=['common.py'],prompt_pipeline_sha256='bge-source',
        provider_endpoint_fingerprints=dict(llm_base_url='answer',embedding_base_url='bge'),
        top_k=8,min_score=.35,query_rewrite={'max_queries':2,'rerank_query':'original'},
        rerank={'model':'same'},context_expansion={'max_chars':24000})
    qwen=deepcopy(bge);qwen.update(embedding_provider='dashscope',embedding_model='qwen3-vl-embedding',
        embedding_dimensions=2560,embedding_runtime={'api':'dashscope'},prompt_pipeline_sha256='qwen-source')
    qwen['provider_endpoint_fingerprints']['embedding_base_url']='qwen'
    assert comparable_configuration(bge)==comparable_configuration(qwen)
    for change in [dict(min_score=.3),dict(top_k=10),dict(rerank={'model':'different'})]:
        assert comparable_configuration(bge)!=comparable_configuration({**qwen,**change})
    qwen['provider_endpoint_fingerprints']['llm_base_url']='different'
    assert comparable_configuration(bge)!=comparable_configuration(qwen)


def test_cached_rewriter_replays_identical_query_without_billing_or_gold_context():
    question='PFI relationship?';key=sha256(question.encode()).hexdigest()
    cache=dict(queries={key:dict(question=question,status='completed',query='PFI refining relationship?',
        provider_call=dict(response_sha256='original-response'))})
    cls=replay_rewriter(cache,'cache-seal')
    a=cls('model','unused-private-key');b=cls('model','unused-private-key')
    assert a.rewrite(question)==b.rewrite(question)=='PFI refining relationship?'
    assert a.last_call['api_calls']==0 and a.last_call['usage'] is None
    assert a.last_call['cache_sha256']=='cache-seal' and 'unused-private-key' not in repr(a.last_call)
    with pytest.raises(ValueError):a.rewrite('Different question')


def test_failed_shared_rewrite_remains_identical_original_only_fallback():
    question='Question?';key=sha256(question.encode()).hexdigest()
    cls=replay_rewriter(dict(queries={key:dict(question=question,status='failed_original_only',provider_call={})}),'seal')
    rewriter=cls()
    with pytest.raises(ProviderError):rewriter.rewrite(question)
    assert rewriter.last_call['api_calls']==0

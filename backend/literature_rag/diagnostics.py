"""Allowlisted, credential-free configuration and provider usage snapshots."""
from hashlib import sha256
from pathlib import Path

from .config import Settings


def configuration_snapshot(env_file: Path):
    settings = Settings(_env_file=env_file)
    root = Path(__file__).resolve().parent
    sources = ['application/prompts.py', 'application/citations.py', 'application/answer_question.py',
               'application/retrieve.py', 'adapters/providers/deepseek.py', 'adapters/providers/openai.py']
    if settings.context_expansion_enabled:
        sources += ['application/context.py','domain/models.py','adapters/sqlite/metadata_store.py']
    if settings.table_retrieval_enabled:
        sources += ['application/table_evidence.py']
    if settings.rerank_enabled:
        sources += ['application/rerank.py','adapters/providers/rerank.py']
    fingerprint = sha256(b'\n'.join((root / source).read_bytes() for source in sources)).hexdigest()
    result = {**{key: getattr(settings, key) for key in (
        'embedding_provider', 'embedding_model', 'embedding_dimensions', 'llm_provider', 'llm_model', 'top_k', 'min_score')},
        'pipeline_version': 'literature-history-v1', 'prompt_pipeline_sha256': fingerprint}
    for key in ('llm_thinking_enabled', 'llm_reasoning_effort'):
        if getattr(settings, key) is not None:
            result[key] = getattr(settings, key)
    if settings.context_expansion_enabled:
        result.update(pipeline_version='literature-context-v1',pipeline_source_files=sources,
                      context_expansion={key:getattr(settings,key) for key in (
                          'context_expansion_enabled','context_neighbor_radius','context_max_evidence_chars','context_max_total_chars')})
    if settings.table_retrieval_enabled:
        result.update(pipeline_version='literature-table-evidence-v1',pipeline_source_files=sources,
            table_retrieval=dict(enabled=True,version='table-evidence-v1',row_cosine='exact',
                parent_fusion='maximum_cosine',max_parent_candidates=50,
                linked_sources_per_context=2,max_linked_sources=8,normal_region_sampling=False))
    if settings.rerank_enabled:
        result.update(pipeline_version='literature-candidate-rerank-v1',pipeline_source_files=sources,
            rerank=dict(enabled=True,version='candidate-rerank-v1',provider=settings.rerank_provider,
                model=settings.rerank_model,timeout_seconds=settings.rerank_timeout_seconds,
                endpoint_sha256=sha256(settings.rerank_base_url.encode()).hexdigest(),
                max_candidates=50,max_chunks_per_doc=1024,overlap_tokens=80,
                input='full_parent_source_text',application_truncation=False,
                retry_count=0,error_policy='fail_without_vector_fallback',score_threshold=None))
    return result


def provider_usage(response):
    usage = getattr(response, 'usage', None)
    if usage is None:
        return None
    fields = ('prompt_tokens', 'completion_tokens', 'input_tokens', 'output_tokens', 'total_tokens')
    result = {key: value for key in fields if type(value := getattr(usage, key, None)) is int and value >= 0}
    for group, names in [('completion_tokens_details', ('reasoning_tokens',)),
                         ('prompt_tokens_details', ('cached_tokens',))]:
        details = getattr(usage, group, None)
        for key in names:
            value = getattr(details, key, None)
            if type(value) is int and value >= 0:
                result[key] = value
    return result or None

"""One bounded inference process; no database credentials or raw provider errors in output."""
import json
import os
import sys
from pathlib import Path

# Executed with -I; import only the checked-in core, never the old project.
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ['ANONYMIZED_TELEMETRY'] = 'False'


def main():
    from time import perf_counter
    worker_started=perf_counter()
    import sqlite3
    from dataclasses import asdict
    from literature_rag.config import Settings
    from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    from literature_rag.adapters.providers.openai import OpenAIEmbedder, OpenAIGenerator
    from literature_rag.adapters.providers.deepseek import DeepSeekGenerator
    from literature_rag.application.retrieve import RetrievalService
    from literature_rag.application.context import ContextOptions
    from literature_rag.application.answer_question import AnswerService
    from literature_rag.application.citations import RecordingCitationValidator
    from literature_rag.diagnostics import configuration_snapshot, combined_usage
    from literature_rag.domain.errors import ProviderError, InfrastructureError

    body = json.loads(sys.stdin.read())
    root = Path(body['data_dir']).resolve()
    if not (root / 'chroma/chroma.sqlite3').is_file():
        raise FileNotFoundError('missing vector index')
    settings = Settings(_env_file=Path(__file__).resolve().parent / '.env.literature')
    if settings.embedding_provider not in ('openai', 'dashscope') or settings.llm_provider not in ('openai', 'deepseek'):
        raise ValueError('unsupported provider')
    if not all((settings.embedding_api_key, settings.embedding_model, settings.embedding_dimensions, settings.llm_api_key, settings.llm_model)):
        raise ValueError('missing configuration')

    class ReadOnlyMetadata(SqliteMetadataStore):
        def _connect(self):
            conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
            return conn

    metadata = ReadOnlyMetadata(root / 'metadata.sqlite3')
    embedder_type = OpenAIEmbedder
    if settings.embedding_provider == 'dashscope':
        from literature_rag.adapters.providers.dashscope import DashScopeEmbedder
        embedder_type = DashScopeEmbedder
    embedder = embedder_type(settings.embedding_model, settings.embedding_dimensions,
                             settings.embedding_api_key.get_secret_value(), settings.embedding_base_url)
    vectors = ChromaVectorStore(root / 'chroma', settings.embedding_provider,
                                settings.embedding_model, settings.embedding_dimensions)
    table_relations = None
    if settings.table_retrieval_enabled:
        from literature_rag.application.table_evidence import TableRelations, TableVectorSearch
        table_relations = TableRelations.load(root, metadata, settings.embedding_provider,
                                             settings.embedding_model, settings.embedding_dimensions)
        vectors = TableVectorSearch(vectors, table_relations)
    visual_catalog=None
    if settings.visual_retrieval_enabled:
        from literature_rag.application.visual_evidence import VisualCatalog,VisualVectorSearch
        visual_catalog=VisualCatalog.load(root,metadata,settings.embedding_provider,
            settings.embedding_model,settings.embedding_dimensions)
        vectors=VisualVectorSearch(vectors,visual_catalog)
    generator_type = DeepSeekGenerator if settings.llm_provider == 'deepseek' else OpenAIGenerator
    generation_options = ({'thinking_enabled': settings.llm_thinking_enabled,
                           'reasoning_effort': settings.llm_reasoning_effort}
                          if settings.llm_provider == 'deepseek' else {
                              'reasoning_effort': settings.llm_reasoning_effort,
                              'timeout_seconds': settings.llm_timeout_seconds,
                              'proxy_url': settings.llm_proxy_url,
                              'actor_authorization': settings.llm_actor_authorization.get_secret_value()
                                  if settings.llm_actor_authorization else None})
    if settings.visual_retrieval_enabled:generation_options['visual_root']=root
    generator = generator_type(settings.llm_model, settings.llm_api_key.get_secret_value(), settings.llm_base_url,
                               answer_guidance_enabled=settings.answer_guidance_enabled,**generation_options)
    evidence_reviewer=None
    if getattr(settings,'evidence_review_enabled',False):
        from literature_rag.application.evidence_review import EvidenceReviewService
        from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
        review_provider=DeepSeekEvidenceReviewer(settings.llm_model,settings.llm_api_key.get_secret_value(),
            settings.llm_base_url,thinking_enabled=settings.llm_thinking_enabled,
            reasoning_effort=settings.llm_reasoning_effort,timeout_seconds=settings.evidence_review_timeout_seconds,
            max_output_tokens=settings.evidence_review_max_output_tokens,
            visual_root=root if settings.visual_retrieval_enabled else None)
        budget=body.get('request_timeout_seconds',300)
        budget=budget if type(budget) is int and 5<=budget<=300 else 300
        evidence_reviewer=EvidenceReviewService(review_provider,visual_root=root if settings.visual_retrieval_enabled else None,
            deadline=worker_started+budget-5)
    query_rewriter=None
    if settings.query_rewrite_enabled:
        from literature_rag.adapters.providers.query_rewrite import DeepSeekQueryRewriter
        query_rewriter=DeepSeekQueryRewriter(settings.query_rewrite_model or settings.llm_model,
            (settings.query_rewrite_api_key or settings.llm_api_key).get_secret_value(),
            settings.query_rewrite_base_url or settings.llm_base_url,settings.query_rewrite_timeout_seconds)
    reranker=None
    rerank_calls=[]
    if settings.rerank_enabled:
        from literature_rag.adapters.providers.rerank import SiliconFlowReranker
        provider_reranker=SiliconFlowReranker(settings.rerank_model,settings.rerank_api_key.get_secret_value(),
            settings.rerank_base_url,settings.rerank_timeout_seconds)

        class CapturedReranker:
            def rerank(self,*args):
                try:return provider_reranker.rerank(*args)
                finally:
                    if provider_reranker.last_call is not None:rerank_calls.append(provider_reranker.last_call)
        reranker=CapturedReranker()
    evidence_by_chunk = {}
    generation_calls = []
    generated_answers = []
    citation_validator = RecordingCitationValidator(attempt_number=lambda: len(generation_calls))
    configuration = configuration_snapshot(Path(__file__).resolve().parent / '.env.literature')
    configuration['documents'] = [
        {'document_id': doc.id, 'filename': doc.filename, 'file_hash': doc.file_hash}
        for doc in metadata.list_documents() if doc.status.value == 'completed'
    ]
    if (root/'structure.json').is_file():
        from hashlib import sha256
        configuration['library_structure_sha256']=sha256((root/'structure.json').read_bytes()).hexdigest()
    seed_evidence=[]
    context_diagnostics={}
    query_embedding_calls=[]

    class CapturedGenerator:
        model_name = generator.model_name

        def generate(self, *args):
            call = {'attempt': len(generation_calls) + 1, 'usage': None, 'outcome': 'failed'}
            generation_calls.append(call)
            try:
                result = generator.generate(*args)
                generated_answers.append(result)
                call['outcome'] = 'generated'
                return result
            finally:
                call['usage'] = getattr(generator, 'last_usage', None)
                call['model_info'] = getattr(generator, 'last_model_info', None)

    class CapturedRetriever(RetrievalService):
        def retrieve(self, *args):
            try:evidences = super().retrieve(*args)
            finally:
                seed_evidence.extend(asdict(e) for e in self.last_seed_evidences)
                context_diagnostics.update(self.last_context_diagnostics)
                if settings.rerank_enabled:context_diagnostics['rerank']=self.last_rerank_diagnostics
                if settings.query_rewrite_enabled:
                    context_diagnostics['query_rewrite']=self.last_query_diagnostics
                    query_embedding_calls.extend(self.last_query_embedding_calls)
            evidence_by_chunk.update({e.chunk_id: e for e in evidences})
            return evidences

    try:
        context_options=ContextOptions(settings.context_expansion_enabled,settings.context_neighbor_radius,
                                      settings.context_max_evidence_chars,settings.context_max_total_chars)
        body_context_catalog=None
        if settings.context_expansion_strategy=='body_section':
            from literature_rag.application.body_context import BodySectionCatalog
            body_context_catalog=BodySectionCatalog.load(root,metadata)
        service = AnswerService(CapturedRetriever(metadata, vectors, embedder,context_options,table_relations,reranker,
            body_context_catalog=body_context_catalog,query_rewriter=query_rewriter,
            query_rewrite_mode=settings.query_rewrite_mode if settings.query_rewrite_enabled else 'dual',
            visual_catalog=visual_catalog,visual_max_images=settings.visual_max_images,
            visual_max_total_bytes=settings.visual_max_total_bytes), CapturedGenerator(), citation_validator,
            reviewer=evidence_reviewer)
        answer = service.answer(body['question'], settings.top_k, settings.min_score)
    except (ProviderError, InfrastructureError) as error:
        print(json.dumps({'status': 'failed', 'answer': '', 'citations': [],
                          'reason_code': 'provider_error' if isinstance(error, ProviderError) else 'retrieval_error',
                          'error_status': 503, 'configuration': configuration,
                          'retrieved_evidence': [asdict(e) for e in evidence_by_chunk.values()],
                          'retrieval_seed_evidence': seed_evidence, 'context_assembly': context_diagnostics,
                          'embedding_usage': combined_usage(query_embedding_calls) if settings.query_rewrite_enabled else getattr(embedder, 'last_usage', None),
                          **({'query_embedding_calls':query_embedding_calls,'query_rewrite_calls':
                              [query_rewriter.last_call] if query_rewriter.last_call else []} if settings.query_rewrite_enabled else {}),
                          **({'rerank_calls':rerank_calls} if settings.rerank_enabled else {}),
                          'generation_calls': generation_calls, 'citation_validation': citation_validator.snapshot(),
                          **({'evidence_review':evidence_reviewer.last_trace} if evidence_reviewer is not None else {}),
                          'claims': [], 'latency_ms': 0}, ensure_ascii=False))
        return
    citations = []
    for citation in answer.citations:
        evidence = evidence_by_chunk[citation.chunk_id]
        citations.append({**asdict(citation), 'document_id': evidence.document_id, 'excerpt': evidence.text})
    print(json.dumps({'status': answer.status.value, 'answer': answer.answer, 'citations': citations,
                      'latency_ms': answer.latency_ms, 'reason_code': answer.reason_code,
                      'configuration': configuration, 'generation_calls': generation_calls,
                      'citation_validation': citation_validator.snapshot(),
                      **({'evidence_review':evidence_reviewer.last_trace} if evidence_reviewer is not None else {}),
                      'embedding_usage': combined_usage(query_embedding_calls) if settings.query_rewrite_enabled else getattr(embedder, 'last_usage', None),
                      **({'query_embedding_calls':query_embedding_calls,'query_rewrite_calls':
                          [query_rewriter.last_call] if query_rewriter.last_call else []} if settings.query_rewrite_enabled else {}),
                      **({'rerank_calls':rerank_calls} if settings.rerank_enabled else {}),
                      'claims': [asdict(claim) for claim in service.last_generated_answer.claims] if answer.status.value == 'answered' else [],
                      'retrieval_seed_evidence': seed_evidence, 'context_assembly': context_diagnostics,
                      'retrieved_evidence': [asdict(e) for e in evidence_by_chunk.values()]}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Intentionally no traceback, question text, key or provider response in HTTP output.
        print(type(error).__name__, file=sys.stderr)
        sys.exit(1)

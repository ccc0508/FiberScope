import logging
from math import isfinite
from time import perf_counter

from literature_rag.domain.errors import InfrastructureError, InputError, ProviderError
from literature_rag.domain.models import Evidence
from literature_rag.application.context import ContextOptions, assemble
from literature_rag.ports.protocols import Embedder, MetadataStore, VectorStore, Reranker, QueryRewriter

logger = logging.getLogger(__name__)
VECTOR_CANDIDATE_LIMIT = 50


def _is_unit_interval_number(value: object) -> bool:
    value_type = type(value)
    if value_type is not int and value_type is not float:
        return False
    if not 0 <= value <= 1:
        return False
    return value_type is int or isfinite(value)


class RetrievalService:
    def __init__(
        self,
        metadata: MetadataStore,
        vectors: VectorStore,
        embedder: Embedder,
        context_options: ContextOptions | None = None,
        table_relations=None,
        reranker: Reranker | None = None,
        body_context_catalog=None,
        query_rewriter: QueryRewriter | None = None,
        query_rewrite_mode: str = 'dual',
        visual_catalog=None,
        visual_max_images: int = 4,
        visual_max_total_bytes: int = 12*1024*1024,
    ) -> None:
        self.metadata = metadata
        self.vectors = vectors
        self.embedder = embedder
        self.context_options = context_options or ContextOptions()
        self.table_relations = table_relations
        self.reranker = reranker
        self.body_context_catalog = body_context_catalog
        self.query_rewriter = query_rewriter
        self.query_rewrite_mode = query_rewrite_mode
        self.visual_catalog=visual_catalog
        self.visual_max_images=visual_max_images
        self.visual_max_total_bytes=visual_max_total_bytes
        if query_rewrite_mode not in {'dual', 'rewrite_only'}:
            raise ValueError('unsupported query rewrite mode')
        if query_rewrite_mode == 'rewrite_only' and query_rewriter is None:
            raise ValueError('rewrite-only retrieval requires a rewriter')
        if query_rewriter is not None and reranker is None:
            raise ValueError('query rewrite retrieval requires reranking')
        if body_context_catalog is not None and not self.context_options.enabled:
            raise ValueError('body-section context requires enabled expansion')
        if body_context_catalog is not None and table_relations is not None:
            table_relations.validate_body_catalog(body_context_catalog)
        self.last_rerank_diagnostics: dict = {}
        self.last_seed_evidences: list[Evidence] = []
        self.last_context_diagnostics: dict = {}
        self.last_query_diagnostics: dict = {}
        self.last_query_embedding_calls: list[dict] = []
        self.last_candidate_evidences: list[Evidence] = []

    def _search(self, question, min_score, branch):
        started = perf_counter()
        call = dict(branch=branch, status='failed', usage=None)
        self.last_query_embedding_calls.append(call)
        try:
            query_embedding = self.embedder.embed_query(question)
            call['status'] = 'completed'
        finally:
            call.update(usage=getattr(self.embedder, 'last_usage', None),
                        latency_ms=int((perf_counter() - started) * 1000))
            if hasattr(self.embedder, 'last_calls'):
                from copy import deepcopy
                call['provider_calls'] = deepcopy(self.embedder.last_calls)
        candidates = self.vectors.search(query_embedding, VECTOR_CANDIDATE_LIMIT)[:VECTOR_CANDIDATE_LIMIT]
        for match in candidates:
            if not _is_unit_interval_number(match.score):
                raise InfrastructureError('vector search returned an invalid score')
        ordered = sorted((m for m in candidates if m.score >= min_score), key=lambda m: -m.score)
        matches, seen = [], set()
        for match in ordered:
            if match.chunk_id not in seen:
                matches.append(match)
                seen.add(match.chunk_id)
        if self.query_rewriter is not None:
            from copy import deepcopy
            self.last_query_diagnostics['branches'].append(dict(branch=branch, query=question,
                raw_candidates=len(candidates), eligible_candidates=len(matches),
                candidates=[dict(chunk_id=m.chunk_id, score=m.score, rank=i+1) for i, m in enumerate(matches)],
                table_retrieval=deepcopy(getattr(self.vectors, 'last_diagnostics', None))))
        return matches

    def retrieve(
        self,
        question: str,
        top_k: int,
        min_score: float,
    ) -> list[Evidence]:
        started = perf_counter()
        self.last_seed_evidences=[]
        self.last_context_diagnostics={}
        self.last_rerank_diagnostics={}
        self.last_query_diagnostics={}
        self.last_query_embedding_calls=[]
        self.last_candidate_evidences=[]
        if not isinstance(question, str):
            raise InputError("question must be a string")
        question = question.strip()
        if not question:
            raise InputError("question must not be empty")
        if type(top_k) is not int or not 1 <= top_k <= VECTOR_CANDIDATE_LIMIT:
            raise InputError("top_k must be between 1 and 50")
        if not _is_unit_interval_number(min_score):
            raise InputError("min_score must be between 0 and 1")

        rewritten = None
        rewrite_only = self.query_rewriter is not None and self.query_rewrite_mode == 'rewrite_only'
        if self.query_rewriter is not None:
            from literature_rag.application.query_rewrite import VERSION, validate_rewrite
            self.last_query_diagnostics = dict(enabled=True, version=VERSION, status='started', branches=[],
                fusion='reciprocal_rank_fusion_k60', max_candidates=VECTOR_CANDIDATE_LIMIT,
                rerank_query='original', answer_query='original')
            if rewrite_only:
                self.last_query_diagnostics.update(mode='rewrite_only',version='rewrite-only-retrieval-and-rerank-v1',
                    fusion='none_single_query',original_query_searched=False,rerank_query='rewritten')
            try:
                rewritten = validate_rewrite(question, self.query_rewriter.rewrite(question))
                self.last_query_diagnostics['status'] = 'unchanged' if rewritten == question else 'rewritten'
                if rewritten == question and not rewrite_only:
                    rewritten = None
            except ProviderError:
                self.last_query_diagnostics['status'] = ('rewrite_failed_no_fallback' if rewrite_only else 'rewrite_failed_original_only')
                if rewrite_only:
                    raise
            finally:
                self.last_query_diagnostics['provider_call'] = getattr(self.query_rewriter, 'last_call', None)
        rerank_question = rewritten if rewrite_only else question
        if rewrite_only:
            self.last_query_diagnostics.update(mode='rewrite_only', fusion='none_single_query',
                original_query_searched=False, rerank_query='rewritten', rerank_query_text=rewritten,
                uniqueness_comparison='not_applicable_without_original_query_search')
            branches = [self._search(rewritten, min_score, 'rewritten')]
        else:
            branches = [self._search(question, min_score, 'original')]
            if rewritten is not None:
                branches.append(self._search(rewritten, min_score, 'rewritten'))
        matches = branches[0]
        all_ids = list(dict.fromkeys(m.chunk_id for branch in branches for m in branch))
        chunks = self.metadata.get_chunks(all_ids)
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        if self.query_rewriter is not None:
            from literature_rag.application.query_rewrite import fuse_candidates
            if len(branches) == 2:
                matches, fused = fuse_candidates(branches, set(chunks_by_id), VECTOR_CANDIDATE_LIMIT)
            else:
                fused = []
            original_ids = set() if rewrite_only else {m.chunk_id for m in branches[0]} & set(chunks_by_id)
            rewritten_ids = ({m.chunk_id for m in branches[0]} & set(chunks_by_id)) if rewrite_only else (
                ({m.chunk_id for m in branches[1]} & set(chunks_by_id)) if len(branches) == 2 else set())
            self.last_query_diagnostics.update(original_candidates=len(original_ids),
                rewritten_candidates=len(rewritten_ids), shared_candidates=len(original_ids & rewritten_ids),
                rewrite_only_candidate_ids=[] if rewrite_only else sorted(rewritten_ids-original_ids),
                unique_candidates=len(original_ids | rewritten_ids), fused_candidates=fused,
                candidate_count_after_budget=sum(m.chunk_id in chunks_by_id for m in matches))
        evidences: list[Evidence] = []
        seen_chunk_ids: set[str] = set()

        for match in matches:
            if match.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(match.chunk_id)
            chunk = chunks_by_id.get(match.chunk_id)
            if chunk is None:
                logger.warning("orphan_vector", extra={"chunk_id": match.chunk_id})
                continue
            evidences.append(
                Evidence(
                    ref=f"[{len(evidences) + 1}]",
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    filename=chunk.filename,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    text=chunk.text,
                    score=match.score,
                )
            )

        if self.reranker is not None:
            from literature_rag.application.rerank import rank_candidates
            self.last_rerank_diagnostics={'enabled':True,'status':'started','candidate_count':len(evidences)}
            evidences,self.last_rerank_diagnostics=rank_candidates(rerank_question,evidences,self.reranker,top_k)
            if self.query_rewriter is not None:
                if rewrite_only:
                    self.last_rerank_diagnostics.update(candidate_order='rewritten-query cosine ranks',
                        query_source='rewritten', query_text=rerank_question,
                        input_policy='Rewritten query and full source chunks, followed by unchanged bounded context assembly.',
                        vector_rank_note='vector_rank denotes the rewritten-query cosine ranking')
                else:
                    self.last_rerank_diagnostics.update(candidate_order='RRF ranks after cross-query deduplication',
                        input_policy='Unmodified user question and full source chunks; candidate pool includes a bounded query rewrite.',
                        vector_rank_note='vector_rank denotes input position in the fused candidate pool, not original-query vector rank')
        self.last_candidate_evidences = list(evidences)
        evidences = evidences[:top_k]
        self.last_seed_evidences = list(evidences)
        if self.body_context_catalog is None:
            evidences,self.last_context_diagnostics=assemble(evidences,self.metadata,self.context_options)
            if self.table_relations is not None:
                from literature_rag.application.table_evidence import append_related_tables
                evidences,self.last_context_diagnostics=append_related_tables(evidences,self.table_relations,
                    self.context_options,self.last_context_diagnostics)
        else:
            from literature_rag.application.body_context import assemble_body_context
            evidences,self.last_context_diagnostics=assemble_body_context(evidences,self.body_context_catalog,
                self.context_options,table_relations=self.table_relations)
        if self.table_relations is not None:
            self.last_context_diagnostics['table_retrieval']=self.vectors.last_diagnostics
        if self.reranker is not None:
            self.last_context_diagnostics['rerank']=self.last_rerank_diagnostics
        if self.query_rewriter is not None:
            added = set(self.last_query_diagnostics['rewrite_only_candidate_ids'])
            selected = {e.chunk_id for e in self.last_seed_evidences}
            final_ids = {s.chunk_id for e in evidences for s in e.source_chunks} | {e.chunk_id for e in evidences}
            self.last_query_diagnostics.update(rewrite_only_selected_ids=sorted(added & selected),
                rewrite_only_final_source_ids=sorted(added & final_ids))
            if rewrite_only:
                self.last_query_diagnostics.update(rewritten_selected_ids=[e.chunk_id for e in self.last_seed_evidences],
                    rewritten_final_source_ids=sorted(final_ids))
            self.last_context_diagnostics['query_rewrite'] = self.last_query_diagnostics
        if self.visual_catalog is not None:
            evidences,visual_info=self.visual_catalog.attach(evidences,self.last_seed_evidences,question,
                self.visual_max_images,self.visual_max_total_bytes)
            self.last_context_diagnostics['visual_evidence']=visual_info
            self.last_context_diagnostics['visual_retrieval']=getattr(self.vectors,'last_visual_diagnostics',{})
        logger.info(
            "retrieval_complete",
            extra={
                "stage": "retrieval",
                "latency_ms": int((perf_counter() - started) * 1000),
                "top_k": top_k,
                "result_count": len(evidences),
                "min_score": min_score,
            },
        )
        return evidences

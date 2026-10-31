import logging
from math import isfinite
from time import perf_counter

from literature_rag.domain.errors import InfrastructureError, InputError
from literature_rag.domain.models import Evidence
from literature_rag.application.context import ContextOptions, assemble
from literature_rag.ports.protocols import Embedder, MetadataStore, VectorStore, Reranker

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
    ) -> None:
        self.metadata = metadata
        self.vectors = vectors
        self.embedder = embedder
        self.context_options = context_options or ContextOptions()
        self.table_relations = table_relations
        self.reranker = reranker
        self.body_context_catalog = body_context_catalog
        if body_context_catalog is not None and not self.context_options.enabled:
            raise ValueError('body-section context requires enabled expansion')
        if body_context_catalog is not None and table_relations is not None:
            table_relations.validate_body_catalog(body_context_catalog)
        self.last_rerank_diagnostics: dict = {}
        self.last_seed_evidences: list[Evidence] = []
        self.last_context_diagnostics: dict = {}

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
        if not isinstance(question, str):
            raise InputError("question must be a string")
        question = question.strip()
        if not question:
            raise InputError("question must not be empty")
        if type(top_k) is not int or not 1 <= top_k <= VECTOR_CANDIDATE_LIMIT:
            raise InputError("top_k must be between 1 and 50")
        if not _is_unit_interval_number(min_score):
            raise InputError("min_score must be between 0 and 1")

        query_embedding = self.embedder.embed_query(question)
        candidates = self.vectors.search(query_embedding, VECTOR_CANDIDATE_LIMIT)[
            :VECTOR_CANDIDATE_LIMIT
        ]
        matches = []
        for match in candidates:
            if not _is_unit_interval_number(match.score):
                raise InfrastructureError("vector search returned an invalid score")
            if match.score >= min_score:
                matches.append(match)
        matches.sort(key=lambda match: match.score, reverse=True)

        chunks = self.metadata.get_chunks([match.chunk_id for match in matches])
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
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
            evidences,self.last_rerank_diagnostics=rank_candidates(question,evidences,self.reranker,top_k)
        evidences = evidences[:top_k]
        self.last_seed_evidences = list(evidences)
        if self.body_context_catalog is None:
            evidences,self.last_context_diagnostics=assemble(evidences,self.metadata,self.context_options)
        else:
            from literature_rag.application.body_context import assemble_body_context
            evidences,self.last_context_diagnostics=assemble_body_context(evidences,self.body_context_catalog,self.context_options)
        if self.table_relations is not None:
            from literature_rag.application.table_evidence import append_related_tables
            evidences,self.last_context_diagnostics=append_related_tables(evidences,self.table_relations,self.context_options,
                self.last_context_diagnostics,body_catalog=self.body_context_catalog)
            self.last_context_diagnostics['table_retrieval']=self.vectors.last_diagnostics
        if self.reranker is not None:
            self.last_context_diagnostics['rerank']=self.last_rerank_diagnostics
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

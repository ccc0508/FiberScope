import logging
from collections.abc import Sequence
from dataclasses import replace
from math import inf, nan

import pytest

from literature_rag.application.retrieve import RetrievalService
from literature_rag.domain.errors import InfrastructureError, InputError
from literature_rag.domain.models import Chunk, Evidence, VectorMatch, VectorRecord
from tests.literature_fakes import InMemoryMetadataStore, InMemoryVectorStore, SpyEmbedder


class ScriptedVectorStore:
    def __init__(self, matches: Sequence[VectorMatch]) -> None:
        self.matches = list(matches)
        self.search_calls: list[tuple[tuple[float, ...], int]] = []

    def search(
        self,
        query_embedding: Sequence[float],
        top_k: int,
    ) -> list[VectorMatch]:
        self.search_calls.append((tuple(query_embedding), top_k))
        return self.matches[:top_k]


class QuerySpyEmbedder(SpyEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.query_calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return super().embed_query(text)


def make_chunk() -> Chunk:
    return Chunk(
        id="chk_1",
        document_id="doc_1",
        filename="paper.pdf",
        page_start=3,
        page_end=3,
        chunk_index=0,
        text="fiber strength evidence",
        token_count=3,
        embedding_model="fake-embed-v1",
    )


def test_retrieval_uses_authoritative_metadata_for_evidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    metadata = InMemoryMetadataStore()
    chunk = make_chunk()
    metadata.chunks[chunk.id] = chunk
    vectors = InMemoryVectorStore()
    vectors.upsert(
        [
            VectorRecord(
                chunk_id=chunk.id,
                document_id="doc_stale",
                filename="stale.pdf",
                page_start=99,
                page_end=99,
                text="stale vector text",
            )
        ],
        [[1.0, 1.0, 0.0]],
    )
    service = RetrievalService(metadata, vectors, SpyEmbedder())
    caplog.set_level(logging.INFO, logger="literature_rag.application.retrieve")

    evidences = service.retrieve("fiber strength", top_k=8, min_score=0.35)

    assert evidences == [
        Evidence(
            ref="[1]",
            chunk_id="chk_1",
            document_id="doc_1",
            filename="paper.pdf",
            page_start=3,
            page_end=3,
            text="fiber strength evidence",
            score=1.0,
        )
    ]
    completed = next(record for record in caplog.records if record.message == "retrieval_complete")
    assert completed.stage == "retrieval"
    assert isinstance(completed.latency_ms, int)
    assert completed.top_k == 8
    assert completed.result_count == 1
    assert completed.min_score == 0.35


def test_retrieval_skips_orphan_vectors_and_low_scoring_matches(
    caplog: pytest.LogCaptureFixture,
) -> None:
    metadata = InMemoryMetadataStore()
    vectors = InMemoryVectorStore()
    vectors.upsert(
        [
            VectorRecord(
                chunk_id="chk_orphan",
                document_id="doc_orphan",
                filename="orphan.pdf",
                page_start=1,
                page_end=1,
                text="fiber strength orphan",
            )
        ],
        [[1.0, 1.0, 0.0]],
    )
    service = RetrievalService(metadata, vectors, SpyEmbedder())
    caplog.set_level(logging.WARNING, logger="literature_rag.application.retrieve")

    assert service.retrieve("fiber strength", top_k=8, min_score=0.35) == []

    orphan = next(record for record in caplog.records if record.message == "orphan_vector")
    assert orphan.chunk_id == "chk_orphan"

    vectors.records.clear()
    chunk = make_chunk()
    metadata.chunks[chunk.id] = chunk
    vectors.upsert(
        [
            VectorRecord(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
            )
        ],
        [[0.0, 0.0, 0.1]],
    )

    assert service.retrieve("fiber strength", top_k=8, min_score=0.35) == []


@pytest.mark.parametrize(
    ("question", "top_k", "min_score", "message"),
    [
        (None, 8, 0.35, "question must be a string"),
        ("   ", 8, 0.35, "question must not be empty"),
        ("fiber", True, 0.35, "top_k must be between 1 and 50"),
        ("fiber", 1.5, 0.35, "top_k must be between 1 and 50"),
        ("fiber", 0, 0.35, "top_k must be between 1 and 50"),
        ("fiber", 51, 0.35, "top_k must be between 1 and 50"),
        ("fiber", 8, True, "min_score must be between 0 and 1"),
        ("fiber", 8, nan, "min_score must be between 0 and 1"),
        ("fiber", 8, inf, "min_score must be between 0 and 1"),
        pytest.param(
            "fiber",
            8,
            10**10000,
            "min_score must be between 0 and 1",
            id="huge-positive-min-score",
        ),
        pytest.param(
            "fiber",
            8,
            -(10**10000),
            "min_score must be between 0 and 1",
            id="huge-negative-min-score",
        ),
        ("fiber", 8, -0.01, "min_score must be between 0 and 1"),
        ("fiber", 8, 1.01, "min_score must be between 0 and 1"),
    ],
)
def test_retrieval_validates_inputs(
    question: object,
    top_k: object,
    min_score: object,
    message: str,
) -> None:
    service = RetrievalService(
        InMemoryMetadataStore(),
        InMemoryVectorStore(),
        SpyEmbedder(),
    )

    with pytest.raises(InputError, match=f"^{message}$"):
        service.retrieve(question, top_k=top_k, min_score=min_score)


def test_retrieval_embeds_the_trimmed_question() -> None:
    embedder = QuerySpyEmbedder()
    service = RetrievalService(
        InMemoryMetadataStore(),
        ScriptedVectorStore([]),
        embedder,
    )

    service.retrieve("  fiber strength \n", top_k=8, min_score=0.35)

    assert embedder.query_calls == ["fiber strength"]


def test_retrieval_keeps_threshold_boundary_and_numbers_after_orphans() -> None:
    metadata = InMemoryMetadataStore()
    chunk = make_chunk()
    metadata.chunks[chunk.id] = chunk
    vectors = InMemoryVectorStore()
    vectors.upsert(
        [
            VectorRecord(
                chunk_id="chk_orphan",
                document_id="doc_orphan",
                filename="orphan.pdf",
                page_start=1,
                page_end=1,
                text="orphan",
            ),
            VectorRecord(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
            ),
        ],
        [[1.0, 1.0, 0.0], [0.35, 0.0, 0.0]],
    )
    service = RetrievalService(metadata, vectors, SpyEmbedder())

    evidences = service.retrieve("fiber strength", top_k=8, min_score=0.35)

    assert [(evidence.ref, evidence.chunk_id, evidence.score) for evidence in evidences] == [
        ("[1]", "chk_1", 0.35)
    ]


def test_retrieval_requests_bounded_candidates_to_fill_final_top_k_after_orphans() -> None:
    metadata = InMemoryMetadataStore()
    chunk = make_chunk()
    metadata.chunks[chunk.id] = chunk
    vectors = ScriptedVectorStore(
        [
            VectorMatch(chunk_id="chk_orphan", score=0.99),
            VectorMatch(chunk_id=chunk.id, score=0.8),
        ]
    )
    service = RetrievalService(metadata, vectors, SpyEmbedder())

    evidences = service.retrieve("fiber strength", top_k=1, min_score=0.35)

    assert [(evidence.ref, evidence.chunk_id) for evidence in evidences] == [("[1]", "chk_1")]
    assert vectors.search_calls == [((1.0, 1.0, 0.0), 50)]


def test_retrieval_stably_sorts_deduplicates_and_applies_final_top_k() -> None:
    metadata = InMemoryMetadataStore()
    highest_duplicate = make_chunk()
    equal_first = replace(
        highest_duplicate,
        id="chk_equal_first",
        chunk_index=1,
        text="equal first evidence",
    )
    equal_second = replace(
        highest_duplicate,
        id="chk_equal_second",
        chunk_index=2,
        text="equal second evidence",
    )
    ignored = replace(
        highest_duplicate,
        id="chk_ignored",
        chunk_index=3,
        text="ignored evidence",
    )
    metadata.chunks.update(
        (chunk.id, chunk) for chunk in (highest_duplicate, equal_first, equal_second, ignored)
    )
    vectors = ScriptedVectorStore(
        [
            VectorMatch(chunk_id=ignored.id, score=0.4),
            VectorMatch(chunk_id=equal_first.id, score=0.8),
            VectorMatch(chunk_id=highest_duplicate.id, score=0.6),
            VectorMatch(chunk_id="chk_orphan", score=0.99),
            VectorMatch(chunk_id=equal_second.id, score=0.8),
            VectorMatch(chunk_id=highest_duplicate.id, score=0.95),
        ]
    )
    service = RetrievalService(metadata, vectors, SpyEmbedder())

    evidences = service.retrieve("fiber strength", top_k=3, min_score=0.35)

    assert [(evidence.ref, evidence.chunk_id, evidence.score) for evidence in evidences] == [
        ("[1]", "chk_1", 0.95),
        ("[2]", "chk_equal_first", 0.8),
        ("[3]", "chk_equal_second", 0.8),
    ]
    assert vectors.search_calls == [((1.0, 1.0, 0.0), 50)]


@pytest.mark.parametrize(
    "score",
    [
        True,
        "0.9",
        nan,
        inf,
        pytest.param(10**10000, id="huge-positive-score"),
        pytest.param(-(10**10000), id="huge-negative-score"),
        -0.01,
        1.01,
    ],
)
def test_retrieval_rejects_invalid_vector_match_scores(score: object) -> None:
    vectors = ScriptedVectorStore([VectorMatch(chunk_id="chk_1", score=score)])
    service = RetrievalService(
        InMemoryMetadataStore(),
        vectors,
        SpyEmbedder(),
    )

    with pytest.raises(
        InfrastructureError,
        match=r"^vector search returned an invalid score$",
    ):
        service.retrieve("fiber strength", top_k=1, min_score=0.35)

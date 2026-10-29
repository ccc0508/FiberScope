from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(UTC)


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    page_number: int
    chunk_index: int
    text: str
    token_count: int


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    filename: str
    file_path: Path
    file_hash: str
    file_size: int
    status: DocumentStatus
    page_count: int = 0
    chunk_count: int = 0
    error_message: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    document_id: str
    filename: str
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    token_count: int
    embedding_model: str
    created_at: datetime = field(default_factory=utc_now)
    kind: str = 'text'


@dataclass(frozen=True, slots=True)
class VectorRecord:
    chunk_id: str
    document_id: str
    text: str
    page_start: int
    page_end: int
    filename: str


@dataclass(frozen=True, slots=True)
class VectorMatch:
    chunk_id: str
    score: float


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    chunk_id: str
    chunk_index: int
    page_start: int
    page_end: int
    text: str
    kind: str = 'text'


@dataclass(frozen=True, slots=True)
class Evidence:
    ref: str
    chunk_id: str
    document_id: str
    filename: str
    page_start: int
    page_end: int
    text: str
    score: float
    source_chunks: tuple[EvidenceSource, ...] = ()
    seed_chunk_ids: tuple[str, ...] = ()
    context_status: str = 'original'


@dataclass(frozen=True, slots=True)
class GeneratedClaim:
    text: str
    citation_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratedAnswer:
    answer: str
    claims: tuple[GeneratedClaim, ...]


@dataclass(frozen=True, slots=True)
class Citation:
    ref: str
    filename: str
    page_start: int
    page_end: int
    chunk_id: str
    source_chunks: tuple[EvidenceSource, ...] = ()


@dataclass(frozen=True, slots=True)
class Answer:
    status: AnswerStatus
    answer: str
    rationale: tuple[str, ...]
    citations: tuple[Citation, ...]
    retrieved_chunk_ids: tuple[str, ...]
    model: str | None
    latency_ms: int
    reason_code: str | None = None

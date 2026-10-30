from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from literature_rag.domain.models import (
    Chunk,
    Document,
    DocumentStatus,
    Evidence,
    GeneratedAnswer,
    PageText,
    VectorMatch,
    VectorRecord,
)


class PageParser(Protocol):
    def parse(self, path: Path) -> list[PageText]:
        raise NotImplementedError


class MetadataStore(Protocol):
    def initialize(self) -> None:
        raise NotImplementedError

    def get_document_by_hash(self, file_hash: str) -> Document | None:
        raise NotImplementedError

    def upsert_document(self, document: Document) -> None:
        raise NotImplementedError

    def update_status(self, document_id: str, status: DocumentStatus) -> None:
        raise NotImplementedError

    def complete_document(self, document_id: str, page_count: int, chunks: Sequence[Chunk]) -> None:
        raise NotImplementedError

    def mark_failed(self, document_id: str, message: str) -> None:
        raise NotImplementedError

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[Chunk]:
        raise NotImplementedError

    def get_context_chunks(self, chunk_ids: Sequence[str], radius: int) -> list[Chunk]:
        raise NotImplementedError

    def list_documents(self) -> list[Document]:
        raise NotImplementedError

    def delete_chunks(self, document_id: str) -> None:
        raise NotImplementedError


class VectorStore(Protocol):
    def upsert(
        self,
        records: Sequence[VectorRecord],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        raise NotImplementedError

    def delete_document(self, document_id: str) -> None:
        raise NotImplementedError

    def search(self, query_embedding: Sequence[float], top_k: int) -> list[VectorMatch]:
        raise NotImplementedError


class Embedder(Protocol):
    @property
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    def dimensions(self) -> int:
        raise NotImplementedError

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


class Reranker(Protocol):
    def rerank(self, question: str, texts: Sequence[str]) -> list[float]:
        """Return one finite relevance score per input, in original input order."""
        raise NotImplementedError


class Generator(Protocol):
    @property
    def model_name(self) -> str:
        raise NotImplementedError

    def generate(
        self,
        question: str,
        evidences: Sequence[Evidence],
        retry_feedback: str | None = None,
    ) -> GeneratedAnswer:
        raise NotImplementedError

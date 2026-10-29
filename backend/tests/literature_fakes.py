from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from literature_rag.domain.models import (
    Chunk,
    Document,
    DocumentStatus,
    Evidence,
    GeneratedAnswer,
    GeneratedClaim,
    PageText,
    VectorMatch,
    VectorRecord,
    utc_now,
)


class FakeParser:
    def __init__(self, pages: Sequence[PageText]) -> None:
        self.pages = list(pages)
        self.calls = 0

    def parse(self, path: Path) -> list[PageText]:
        self.calls += 1
        return list(self.pages)


class SpyEmbedder:
    model_name = "fake-embed-v1"
    dimensions = 3

    def __init__(self) -> None:
        self.document_calls = 0
        self.document_batches: list[tuple[str, ...]] = []
        self.query_count = 0
        self.query_texts: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += 1
        self.document_batches.append(tuple(texts))
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_count += 1
        self.query_texts.append(text)
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> list[float]:
        normalized = text.lower()
        embedding = [
            float(normalized.count("fiber")),
            float(normalized.count("strength")),
            float(normalized.count("unrelated")),
        ]
        return embedding if any(embedding) else [0.001, 0.001, 0.001]


class FakeGenerator:
    model_name = "fake-llm-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.questions: list[str] = []
        self.evidence_batches: list[tuple[Evidence, ...]] = []
        self.retry_feedbacks: list[str | None] = []

    def generate(
        self,
        question: str,
        evidences: Sequence[Evidence],
        retry_feedback: str | None = None,
    ) -> GeneratedAnswer:
        self.calls += 1
        self.questions.append(question)
        self.evidence_batches.append(tuple(evidences))
        self.retry_feedbacks.append(retry_feedback)
        return GeneratedAnswer(
            answer="Refining is supported by the imported paper. [1]",
            claims=(
                GeneratedClaim(
                    "The imported evidence supports the answer",
                    ("[1]",),
                ),
            ),
        )


class InMemoryMetadataStore:
    def __init__(self, operations: list[str] | None = None) -> None:
        self.documents: dict[str, Document] = {}
        self.chunks: dict[str, Chunk] = {}
        self.fail_complete = False
        self.fail_delete_chunks = False
        self.fail_mark_failed = False
        self.operations = operations if operations is not None else []

    def initialize(self) -> None:
        pass

    def get_document_by_hash(self, file_hash: str) -> Document | None:
        return next(
            (document for document in self.documents.values() if document.file_hash == file_hash),
            None,
        )

    def upsert_document(self, document: Document) -> None:
        existing = self.get_document_by_hash(document.file_hash)
        if existing is None:
            self.documents[document.id] = document
            return
        self.documents[existing.id] = replace(
            existing,
            filename=document.filename,
            file_path=document.file_path,
            file_size=document.file_size,
            status=document.status,
            error_message=document.error_message,
            updated_at=document.updated_at,
        )

    def update_status(self, document_id: str, status: DocumentStatus) -> None:
        self.documents[document_id] = replace(
            self.documents[document_id],
            status=status,
            updated_at=utc_now(),
        )

    def complete_document(
        self,
        document_id: str,
        page_count: int,
        chunks: Sequence[Chunk],
    ) -> None:
        if self.fail_complete:
            raise RuntimeError("forced completion failure")

        self.delete_chunks(document_id)
        self.chunks.update((chunk.id, chunk) for chunk in chunks)
        self.documents[document_id] = replace(
            self.documents[document_id],
            status=DocumentStatus.COMPLETED,
            page_count=page_count,
            chunk_count=len(chunks),
            error_message=None,
            updated_at=utc_now(),
        )

    def mark_failed(self, document_id: str, message: str) -> None:
        self.operations.append("metadata.mark_failed")
        if self.fail_mark_failed:
            raise RuntimeError("forced metadata mark failed failure")
        self.documents[document_id] = replace(
            self.documents[document_id],
            status=DocumentStatus.FAILED,
            error_message=message[:1000],
            updated_at=utc_now(),
        )

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[Chunk]:
        return [self.chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in self.chunks]

    def get_context_chunks(self, chunk_ids: Sequence[str], radius: int) -> list[Chunk]:
        seeds=self.get_chunks(chunk_ids)
        return sorted([c for c in self.chunks.values() if any(
            c.document_id==s.document_id and c.page_start==s.page_start and c.page_end==s.page_end
            and abs(c.chunk_index-s.chunk_index)<=radius for s in seeds)],key=lambda c:(c.document_id,c.chunk_index))

    def list_documents(self) -> list[Document]:
        return list(self.documents.values())

    def delete_chunks(self, document_id: str) -> None:
        self.operations.append("metadata.delete_chunks")
        if self.fail_delete_chunks:
            raise RuntimeError("forced metadata chunk delete failure")
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk.document_id != document_id
        }
        if document_id in self.documents:
            self.documents[document_id] = replace(
                self.documents[document_id],
                chunk_count=0,
                updated_at=utc_now(),
            )


class InMemoryVectorStore:
    dimensions = 3

    def __init__(self, operations: list[str] | None = None) -> None:
        self.records: dict[str, tuple[VectorRecord, list[float]]] = {}
        self.fail_delete_document = False
        self.operations = operations if operations is not None else []

    def upsert(
        self,
        records: Sequence[VectorRecord],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if len(records) != len(embeddings):
            raise ValueError("records and embeddings must have the same length")
        for index, embedding in enumerate(embeddings):
            actual_dimensions = len(embedding)
            if actual_dimensions != self.dimensions:
                raise ValueError(
                    f"embedding at index {index} has {actual_dimensions} dimensions; "
                    f"expected {self.dimensions}"
                )
        for record, embedding in zip(records, embeddings, strict=True):
            self.records[record.chunk_id] = (record, list(embedding))

    def delete_document(self, document_id: str) -> None:
        self.operations.append("vectors.delete_document")
        if self.fail_delete_document:
            raise RuntimeError("forced vector delete failure")
        self.records = {
            chunk_id: stored
            for chunk_id, stored in self.records.items()
            if stored[0].document_id != document_id
        }

    def search(
        self,
        query_embedding: Sequence[float],
        top_k: int,
    ) -> list[VectorMatch]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        actual_dimensions = len(query_embedding)
        if actual_dimensions != self.dimensions:
            raise ValueError(
                f"query embedding has {actual_dimensions} dimensions; expected {self.dimensions}"
            )
        scored = [
            (
                chunk_id,
                sum(
                    query_value * stored_value
                    for query_value, stored_value in zip(
                        query_embedding,
                        embedding,
                        strict=True,
                    )
                ),
            )
            for chunk_id, (_, embedding) in self.records.items()
        ]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [
            VectorMatch(
                chunk_id=chunk_id,
                score=max(0.0, min(1.0, score)),
            )
            for chunk_id, score in scored[:top_k]
        ]

from collections.abc import Sequence
from hashlib import sha256
from math import isfinite
from pathlib import Path

import chromadb

from literature_rag.domain.errors import InfrastructureError
from literature_rag.domain.models import VectorMatch, VectorRecord


def _finite_vector(
    vector: Sequence[float],
    expected_dimensions: int,
    label: str,
) -> list[float]:
    actual_dimensions = len(vector)
    if actual_dimensions != expected_dimensions:
        raise ValueError(
            f"{label} has {actual_dimensions} dimensions; expected {expected_dimensions}"
        )

    normalized: list[float] = []
    for component_index, component in enumerate(vector):
        if type(component) not in (int, float):
            raise ValueError(f"{label} contains an invalid component at index {component_index}")
        try:
            normalized_component = float(component)
        except OverflowError:
            raise ValueError(
                f"{label} contains an invalid component at index {component_index}"
            ) from None
        if not isfinite(normalized_component):
            raise ValueError(f"{label} contains an invalid component at index {component_index}")
        normalized.append(normalized_component)
    return normalized


def _collection_name(collection: object) -> str:
    if isinstance(collection, str):
        return collection
    name = getattr(collection, "name", None)
    if not isinstance(name, str):
        raise InfrastructureError("cannot inspect Chroma collections")
    return name


def _finite_distance(distance: object) -> float:
    if type(distance) not in (int, float):
        raise InfrastructureError("invalid Chroma distance response")
    try:
        normalized = float(distance)
    except OverflowError:
        raise InfrastructureError("invalid Chroma distance response") from None
    if not isfinite(normalized):
        raise InfrastructureError("invalid Chroma distance response")
    return normalized


class ChromaVectorStore:
    def __init__(
        self,
        path: Path,
        provider: str,
        model: str,
        dimensions: int,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")

        self.provider = provider
        self.model = model
        self.dimensions = dimensions
        self.fingerprint = sha256(
            f"{provider}|{model}|{dimensions}".encode("utf-8")  # noqa: UP012
        ).hexdigest()
        self.collection_name = f"chunks_{self.fingerprint[:12]}"

        try:
            path.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(str(path))
            managed_collections = {
                name
                for name in map(_collection_name, self.client.list_collections())
                if name.startswith("chunks_")
            }
            if managed_collections - {self.collection_name}:
                raise InfrastructureError(
                    "Chroma embedding configuration changed; use a fresh data directory and reindex"
                )
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={
                    "fingerprint": self.fingerprint,
                    "provider": provider,
                    "model": model,
                    "dimensions": dimensions,
                },
                configuration={"hnsw": {"space": "cosine"}},
            )
            metadata = self.collection.metadata or {}
            if metadata.get("fingerprint") != self.fingerprint:
                raise InfrastructureError("Chroma embedding fingerprint mismatch")
            if (
                metadata.get("provider") != self.provider
                or metadata.get("model") != self.model
                or metadata.get("dimensions") != self.dimensions
            ):
                raise InfrastructureError("Chroma embedding metadata mismatch")
            configuration = self.collection.configuration or {}
            hnsw_configuration = configuration.get("hnsw") or {}
            if hnsw_configuration.get("space") != "cosine":
                raise InfrastructureError("Chroma distance configuration mismatch")
        except InfrastructureError:
            raise
        except Exception as error:
            raise InfrastructureError("cannot initialize Chroma") from error

    def upsert(
        self,
        records: Sequence[VectorRecord],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        if len(records) != len(embeddings):
            raise ValueError("records and embeddings must have the same length")
        normalized_embeddings = [
            _finite_vector(embedding, self.dimensions, f"embedding at index {index}")
            for index, embedding in enumerate(embeddings)
        ]
        if not records:
            return

        try:
            self.collection.upsert(
                ids=[record.chunk_id for record in records],
                embeddings=normalized_embeddings,
                documents=[record.text for record in records],
                metadatas=[
                    {
                        "document_id": record.document_id,
                        "filename": record.filename,
                        "page_start": record.page_start,
                        "page_end": record.page_end,
                    }
                    for record in records
                ],
            )
        except Exception as error:
            raise InfrastructureError("cannot upsert Chroma vectors") from error

    def delete_document(self, document_id: str) -> None:
        try:
            self.collection.delete(where={"document_id": document_id})
        except Exception as error:
            raise InfrastructureError("cannot delete Chroma document vectors") from error

    def search(
        self,
        query_embedding: Sequence[float],
        top_k: int,
    ) -> list[VectorMatch]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        normalized_query = _finite_vector(
            query_embedding,
            self.dimensions,
            "query embedding",
        )

        try:
            count = self.collection.count()
            if count == 0:
                return []

            result = self.collection.query(
                query_embeddings=[normalized_query],
                n_results=min(top_k, count),
                include=["distances"],
            )
            ids = result["ids"][0]
            distances = (result["distances"] or [[]])[0]
            return [
                VectorMatch(
                    chunk_id=chunk_id,
                    score=max(0.0, min(1.0, 1.0 - _finite_distance(distance))),
                )
                for chunk_id, distance in zip(ids, distances, strict=True)
            ]
        except InfrastructureError:
            raise
        except Exception as error:
            raise InfrastructureError("cannot search Chroma vectors") from error

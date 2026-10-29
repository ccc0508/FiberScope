import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from literature_rag.domain.errors import InfrastructureError
from literature_rag.domain.models import Chunk, Document, DocumentStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    page_start INTEGER NOT NULL CHECK (page_start >= 1),
    page_end INTEGER NOT NULL CHECK (page_end >= page_start),
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    embedding_model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'text',
    UNIQUE (document_id, chunk_index)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteMetadataStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            connection.close()
            raise
        return connection

    @contextmanager
    def _database(
        self,
        error_message: str,
        *,
        create_parent: bool = False,
        include_detail: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        try:
            connection: sqlite3.Connection | None = None
            try:
                if create_parent:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                connection = self._connect()
                with connection:
                    yield connection
            finally:
                if connection is not None:
                    connection.close()
        except (sqlite3.Error, OSError) as error:
            message = f"{error_message}: {error}" if include_detail else error_message
            raise InfrastructureError(message) from error

    def initialize(self) -> None:
        with self._database(
            "cannot initialize SQLite metadata",
            create_parent=True,
            include_detail=True,
        ) as connection:
            connection.executescript(_SCHEMA)
            # Existing libraries remain readable; writers migrate only on explicit initialize.
            if 'kind' not in {row['name'] for row in connection.execute('PRAGMA table_info(chunks)')}:
                connection.execute("ALTER TABLE chunks ADD COLUMN kind TEXT NOT NULL DEFAULT 'text'")

    def upsert_document(self, document: Document) -> None:
        values = (
            document.id,
            document.filename,
            str(document.file_path),
            document.file_hash,
            document.file_size,
            document.page_count,
            document.chunk_count,
            document.status.value,
            document.error_message,
            document.created_at.isoformat(),
            document.updated_at.isoformat(),
        )
        with self._database("cannot upsert SQLite document metadata") as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id, filename, file_path, file_hash, file_size,
                    page_count, chunk_count, status, error_message,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_hash) DO UPDATE SET
                    filename = excluded.filename,
                    file_path = excluded.file_path,
                    file_size = excluded.file_size,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                values,
            )

    def get_document_by_hash(self, file_hash: str) -> Document | None:
        with self._database("cannot get SQLite document metadata") as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE file_hash = ?",
                (file_hash,),
            ).fetchone()
        return self._to_document(row) if row is not None else None

    def update_status(self, document_id: str, status: DocumentStatus) -> None:
        with self._database("cannot update SQLite document status") as connection:
            cursor = connection.execute(
                "UPDATE documents SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, _now(), document_id),
            )
            if cursor.rowcount != 1:
                raise InfrastructureError(
                    "cannot update SQLite document status: document not found"
                )

    def complete_document(
        self,
        document_id: str,
        page_count: int,
        chunks: Sequence[Chunk],
    ) -> None:
        if any(chunk.document_id != document_id for chunk in chunks):
            raise InfrastructureError(
                "cannot complete SQLite document metadata: chunk owner mismatch"
            )

        rows = [
            (
                chunk.id,
                chunk.document_id,
                chunk.filename,
                chunk.page_start,
                chunk.page_end,
                chunk.chunk_index,
                chunk.text,
                chunk.token_count,
                chunk.embedding_model,
                chunk.created_at.isoformat(),
                chunk.kind,
            )
            for chunk in chunks
        ]
        with self._database("cannot complete SQLite document metadata") as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            connection.executemany(
                """
                INSERT INTO chunks (
                    id, document_id, filename, page_start, page_end,
                    chunk_index, text, token_count, embedding_model, created_at, kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            cursor = connection.execute(
                """
                UPDATE documents
                SET status = ?, page_count = ?, chunk_count = ?,
                    error_message = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    DocumentStatus.COMPLETED.value,
                    page_count,
                    len(chunks),
                    _now(),
                    document_id,
                ),
            )
            if cursor.rowcount != 1:
                raise InfrastructureError(
                    "cannot complete SQLite document metadata: document not found"
                )

    def mark_failed(self, document_id: str, message: str) -> None:
        with self._database("cannot mark SQLite document failed") as connection:
            cursor = connection.execute(
                """
                UPDATE documents
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (DocumentStatus.FAILED.value, message[:1000], _now(), document_id),
            )
            if cursor.rowcount != 1:
                raise InfrastructureError("cannot mark SQLite document failed: document not found")

    def delete_chunks(self, document_id: str) -> None:
        with self._database("cannot delete SQLite document chunks") as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            connection.execute(
                """
                UPDATE documents
                SET chunk_count = 0, updated_at = ?
                WHERE id = ?
                """,
                (_now(), document_id),
            )

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[Chunk]:
        if not chunk_ids:
            return []

        placeholders = ", ".join("?" for _ in chunk_ids)
        with self._database("cannot get SQLite chunk metadata") as connection:
            rows = connection.execute(
                f"SELECT * FROM chunks WHERE id IN ({placeholders})",
                tuple(chunk_ids),
            ).fetchall()
        by_id = {row["id"]: self._to_chunk(row) for row in rows}
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    def list_documents(self) -> list[Document]:
        with self._database("cannot list SQLite document metadata") as connection:
            rows = connection.execute(
                "SELECT * FROM documents ORDER BY updated_at DESC, filename"
            ).fetchall()
        return [self._to_document(row) for row in rows]

    def get_context_chunks(self, chunk_ids: Sequence[str], radius: int) -> list[Chunk]:
        if type(radius) is not int or not 0 <= radius <= 2 or len(chunk_ids) > 50:
            raise ValueError('context lookup exceeds its bounds')
        if not chunk_ids:
            return []
        marks=', '.join('?' for _ in chunk_ids)
        with self._database('cannot read neighboring source chunks') as connection:
            rows=connection.execute(
                f'''SELECT DISTINCT c.* FROM chunks c JOIN chunks s
                    ON c.document_id=s.document_id AND c.page_start=s.page_start AND c.page_end=s.page_end
                    AND c.chunk_index BETWEEN s.chunk_index-? AND s.chunk_index+?
                    WHERE s.id IN ({marks}) ORDER BY c.document_id,c.chunk_index''',
                (radius,radius,*chunk_ids),
            ).fetchall()
        return [self._to_chunk(row) for row in rows]

    @staticmethod
    def _to_document(row: sqlite3.Row) -> Document:
        return Document(
            id=row["id"],
            filename=row["filename"],
            file_path=Path(row["file_path"]),
            file_hash=row["file_hash"],
            file_size=row["file_size"],
            status=DocumentStatus(row["status"]),
            page_count=row["page_count"],
            chunk_count=row["chunk_count"],
            error_message=row["error_message"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _to_chunk(row: sqlite3.Row) -> Chunk:
        return Chunk(
            id=row["id"],
            document_id=row["document_id"],
            filename=row["filename"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            token_count=row["token_count"],
            embedding_model=row["embedding_model"],
            created_at=datetime.fromisoformat(row["created_at"]),
            kind=row['kind'] if 'kind' in row.keys() else 'text',
        )

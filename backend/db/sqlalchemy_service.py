import copy
import logging
import os
import asyncio
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    and_,
    cast,
    delete,
    func,
    literal,
    literal_column,
    or_,
    select,
    text,
    update as sql_update,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, insert
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.models import ChatMessage, Document, DocumentChunk, SessionRecord, SessionDocument
from core.config import config
from core.session import NEW_SESSION_LABEL, Session
from db.base import (
    REPLACEMENT_FAILED,
    REPLACEMENT_IN_PROGRESS,
    ChunkMatch,
    ChunkRecord,
    DatabaseService,
)
from db.migration_ledger import MigrationLedgerSchemaError
from db.tenant_scope import require_tenant_id
from services.retrieval_service import (
    SCORE_TYPE_HYBRID_RRF,
    SCORE_TYPE_VECTOR,
    merge_chunk_matches_with_scores,
    reciprocal_rank_fusion_scores,
)

logger = logging.getLogger(__name__)

# Full-text config matches migration 004 (to_tsvector / plainto_tsquery).
_FTS_LANGUAGE = "english"


def _replacement_error_preserving_prior(
    status: str | None,
    existing_error: dict | None,
    status_detail: str | None,
    new_error: dict,
) -> dict:
    """Keep the original failure when a replacement of a failed document also fails.

    A completed document's replacement error replaces any stale error. A failed
    document keeps the error that explains why it has no content under
    ``prior_error``. Later replacement failures keep that same original error
    rather than nesting a history of attempts.
    """
    if (
        status_detail != REPLACEMENT_FAILED
        or status != "failed"
        or not isinstance(existing_error, dict)
        or not existing_error
    ):
        return new_error

    merged = dict(new_error)
    prior = existing_error.get("prior_error")
    if isinstance(prior, dict) and prior:
        merged["prior_error"] = prior
    else:
        merged["prior_error"] = existing_error
    return merged

# Only completed/failed documents may be replaced (staged replacement, migration 014).
_REPLACEABLE_STATUSES = ("completed", "failed")


def _is_missing_content_tsv_error(exc: BaseException) -> bool:
    """True when hybrid migration 004 has not been applied."""
    message = str(exc).lower()
    if "content_tsv" in message and "does not exist" in message:
        return True
    orig = getattr(exc, "__cause__", None) or getattr(exc, "orig", None)
    if orig is not None and orig is not exc:
        return _is_missing_content_tsv_error(orig)
    return False


def _document_row_to_dict(document: Document) -> dict:
    return {
        "id": str(document.id),
        "file_name": document.file_name,
        "tenant_id": document.tenant_id,
        "status": document.status,
        "chunks": document.chunks,
        "error": document.error,
        "artifact_uri": document.artifact_uri,
        "created_at": str(document.created_at) if document.created_at else None,
        "updated_at": str(document.updated_at) if document.updated_at else None,
    }


def _document_status_payload(document: Document) -> dict:
    return {
        "document_id": str(document.id),
        "file_name": document.file_name,
        "status": document.status,
        "status_detail": document.status_detail,
        "chunks": document.chunks,
        "error": document.error,
        "metadata": document.doc_metadata or {},
        "job_metadata": document.job_metadata or {},
        "created_at": str(document.created_at) if document.created_at else None,
        "updated_at": str(document.updated_at) if document.updated_at else None,
    }


def _apply_job_metadata_patch(document: Document, patch: dict | None) -> None:
    if not patch:
        return
    from services.ingestion_job_metadata import merge_job_metadata

    document.job_metadata = merge_job_metadata(document.job_metadata, patch)


class SQLAlchemyService(DatabaseService):
    """
    Development database service using PostgreSQL with pgvector.
    """

    def __init__(self):
        db_url = config.DATABASE_URL
        if not db_url:
            raise ValueError(
                "DATABASE_URL is not set. Set DATABASE_URL to a PostgreSQL connection "
                "string with pgvector enabled."
            )
        async_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

        self.engine = create_async_engine(
            async_url,
            echo=False,
            pool_size=config.SQLALCHEMY_POOL_SIZE,
            max_overflow=config.SQLALCHEMY_MAX_OVERFLOW,
            pool_timeout=config.SQLALCHEMY_POOL_TIMEOUT_SEC,
            connect_args={
                "command_timeout": config.SQLALCHEMY_STATEMENT_TIMEOUT_SEC,
            },
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._retrieval_semaphore = asyncio.Semaphore(config.SQLALCHEMY_RETRIEVAL_CONCURRENCY)

    async def list_applied_migrations(self) -> Optional[list[str]]:
        """Validate and read the migration ledger without changing database state."""

        async with self.async_session() as session:
            schema_result = await session.execute(
                text(
                    """
                    SELECT
                      c.relkind = 'r' AS is_table,
                      (
                        SELECT pg_catalog.count(*) = 2
                        FROM pg_catalog.pg_attribute AS a
                        WHERE a.attrelid = c.oid
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                      ) AS has_only_expected_columns,
                      EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_attribute AS a
                        WHERE a.attrelid = c.oid
                          AND a.attname = 'filename'
                          AND NOT a.attisdropped
                          AND a.atttypid = 'text'::pg_catalog.regtype
                          AND a.attnotnull
                      ) AS filename_is_text_not_null,
                      EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_constraint AS con
                        JOIN pg_catalog.pg_attribute AS a
                          ON a.attrelid = con.conrelid
                         AND a.attnum = ANY (con.conkey)
                        WHERE con.conrelid = c.oid
                          AND con.contype = 'p'
                          AND pg_catalog.cardinality(con.conkey) = 1
                          AND NOT con.condeferrable
                          AND a.attname = 'filename'
                      ) AS filename_is_primary_key,
                      EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_attribute AS a
                        WHERE a.attrelid = c.oid
                          AND a.attname = 'applied_at'
                          AND NOT a.attisdropped
                          AND a.atttypid = 'timestamptz'::pg_catalog.regtype
                          AND a.attnotnull
                      ) AS applied_at_is_timestamptz_not_null,
                      EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_attribute AS a
                        JOIN pg_catalog.pg_attrdef AS d
                          ON d.adrelid = a.attrelid
                         AND d.adnum = a.attnum
                        WHERE a.attrelid = c.oid
                          AND a.attname = 'applied_at'
                          AND NOT a.attisdropped
                          AND pg_catalog.pg_get_expr(d.adbin, d.adrelid) = 'now()'
                      ) AS applied_at_default_is_now
                    FROM pg_catalog.pg_class AS c
                    JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = 'schema_migrations'
                    """
                )
            )
            schema = schema_result.mappings().one_or_none()
            if schema is None:
                return None

            contract_fields = {
                "is_table": "ordinary table",
                "has_only_expected_columns": (
                    "exactly the filename and applied_at columns"
                ),
                "filename_is_text_not_null": "filename TEXT NOT NULL",
                "filename_is_primary_key": (
                    "non-deferrable PRIMARY KEY (filename)"
                ),
                "applied_at_is_timestamptz_not_null": (
                    "applied_at TIMESTAMPTZ NOT NULL"
                ),
                "applied_at_default_is_now": "applied_at DEFAULT now()",
            }
            invalid = [
                description
                for field, description in contract_fields.items()
                if not schema[field]
            ]
            if invalid:
                raise MigrationLedgerSchemaError(
                    "Database migration ledger schema is malformed. Expected "
                    "public.schema_migrations(filename TEXT PRIMARY KEY, "
                    "applied_at TIMESTAMPTZ NOT NULL DEFAULT now()); invalid "
                    f"component(s): {', '.join(invalid)}. Inspect and back up the "
                    "existing relation, repair it to the expected contract, then "
                    "rerun 008_schema_migrations.sql. See "
                    "DEVELOPMENT.md#upgrading-an-existing-database."
                )

            result = await session.execute(
                text(
                    "SELECT filename FROM public.schema_migrations "
                    "ORDER BY filename"
                )
            )
            return list(result.scalars().all())

    async def _document_owned_by_tenant(
        self, session: AsyncSession, doc_id: str, tenant_id: str
    ) -> bool:
        result = await session.execute(
            select(Document.id).where(
                Document.id == doc_id,
                Document.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def create_document(
        self, filename: str, tenant_id: str, metadata: Optional[dict] = None
    ) -> str:
        tenant_id = require_tenant_id(tenant_id, method="create_document")
        async with self.async_session() as session:
            doc_id = str(uuid.uuid4())
            document = Document(
                id=doc_id,
                file_name=filename,
                tenant_id=tenant_id,
                status="uploaded",
                chunks={"total": 0, "processed": 0},
                doc_metadata=metadata or {},
            )
            session.add(document)
            await session.commit()
            logger.info(f"[PostgreSQL] Created document {doc_id}")
            return doc_id

    async def store_chunks_with_embeddings(
        self,
        doc_id: str,
        chunk_records: list[ChunkRecord],
        tenant_id: str,
    ) -> list[str]:
        tenant_id = require_tenant_id(tenant_id, method="store_chunks_with_embeddings")
        async with self.async_session() as session:
            async with session.begin():
                if not await self._document_owned_by_tenant(session, doc_id, tenant_id):
                    raise ValueError(
                        f"store_chunks_with_embeddings: document {doc_id} not found for tenant {tenant_id}"
                    )

                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                )

                chunk_rows = []
                chunk_ids = []

                for record in chunk_records:
                    chunk_id = str(uuid.uuid4())
                    chunk_ids.append(chunk_id)
                    chunk_rows.append(
                        DocumentChunk(
                            id=chunk_id,
                            document_id=doc_id,
                            chunk_text=record.chunk_text,
                            embedding=record.embedding,
                            chunk_index=record.chunk_index,
                            page_number=record.page_number,
                            character_offset_start=record.character_offset_start,
                            character_offset_end=record.character_offset_end,
                        )
                    )

                session.add_all(chunk_rows)

            logger.info(
                "[PostgreSQL] Stored %s chunks for document %s (replace semantics)",
                len(chunk_ids),
                doc_id,
            )
            return chunk_ids

    async def get_document(self, doc_id: str, tenant_id: str) -> dict | None:
        tenant_id = require_tenant_id(tenant_id, method="get_document")
        async with self.async_session() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == doc_id,
                    Document.tenant_id == tenant_id,
                )
            )
            document = result.scalar_one_or_none()
            if not document:
                return None
            return _document_row_to_dict(document)

    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunk_records: list[ChunkRecord],
        tenant_id: str,
    ) -> tuple[str, list[str]]:
        tenant_id = require_tenant_id(tenant_id, method="create_document_with_chunks_atomic")
        async with self.async_session() as session:
            chunk_ids: list[str] = []
            doc_id = str(uuid.uuid4())

            try:
                async with session.begin():
                    document = Document(
                        id=doc_id,
                        file_name=file_name,
                        tenant_id=tenant_id,
                        status="completed",
                        chunks={"total": len(chunk_records), "processed": len(chunk_records)},
                    )
                    session.add(document)

                    for record in chunk_records:
                        chunk_id = str(uuid.uuid4())
                        chunk_ids.append(chunk_id)
                        session.add(
                            DocumentChunk(
                                id=chunk_id,
                                document_id=doc_id,
                                chunk_text=record.chunk_text,
                                embedding=record.embedding,
                                chunk_index=record.chunk_index,
                                page_number=record.page_number,
                                character_offset_start=record.character_offset_start,
                                character_offset_end=record.character_offset_end,
                            )
                        )

                logger.info(f"[PostgreSQL] Atomic upload: {doc_id} with {len(chunk_ids)} chunks")
                return doc_id, chunk_ids
            except Exception as e:
                logger.error(f"[PostgreSQL] Atomic upload failed: {e}")
                raise

    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        tenant_id: str,
        *,
        error: dict | None = None,
        chunks: dict | None = None,
        job_metadata_patch: dict | None = None,
    ) -> None:
        tenant_id = require_tenant_id(tenant_id, method="update_document_status")
        async with self.async_session() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == doc_id,
                    Document.tenant_id == tenant_id,
                )
            )
            document = result.scalar_one_or_none()
            if not document:
                logger.warning(
                    "[PostgreSQL] update_document_status: document %s not found for tenant %s",
                    doc_id,
                    tenant_id,
                )
                return

            document.status = status
            if error is not None:
                document.error = error
            elif status != "failed":
                document.error = None
            if chunks is not None:
                document.chunks = chunks
            _apply_job_metadata_patch(document, job_metadata_patch)
            document.updated_at = datetime.utcnow()

            await session.commit()
            logger.debug(f"[PostgreSQL] Updated status for {doc_id} -> {status}")

    async def set_document_artifact_uri(
        self,
        doc_id: str,
        tenant_id: str,
        artifact_uri: Optional[str],
    ) -> None:
        tenant_id = require_tenant_id(tenant_id, method="set_document_artifact_uri")
        async with self.async_session() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == doc_id,
                    Document.tenant_id == tenant_id,
                )
            )
            document = result.scalar_one_or_none()
            if not document:
                logger.warning(
                    "[PostgreSQL] set_document_artifact_uri: document %s not found for tenant %s",
                    doc_id,
                    tenant_id,
                )
                return

            document.artifact_uri = artifact_uri
            document.updated_at = datetime.utcnow()
            await session.commit()
            logger.debug(
                "[PostgreSQL] Set artifact_uri for %s",
                doc_id,
            )

    async def merge_document_job_metadata(
        self,
        doc_id: str,
        tenant_id: str,
        patch: dict,
    ) -> None:
        tenant_id = require_tenant_id(tenant_id, method="merge_document_job_metadata")
        async with self.async_session() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == doc_id,
                    Document.tenant_id == tenant_id,
                )
            )
            document = result.scalar_one_or_none()
            if not document:
                logger.warning(
                    "[PostgreSQL] merge_document_job_metadata: document %s not found for tenant %s",
                    doc_id,
                    tenant_id,
                )
                return

            _apply_job_metadata_patch(document, patch)
            document.updated_at = datetime.utcnow()
            await session.commit()

    async def get_document_status(self, doc_id: str, tenant_id: str) -> dict | None:
        tenant_id = require_tenant_id(tenant_id, method="get_document_status")
        async with self.async_session() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == doc_id,
                    Document.tenant_id == tenant_id,
                )
            )
            document = result.scalar_one_or_none()
            if not document:
                return None
            return _document_status_payload(document)

    async def begin_document_replacement(self, doc_id: str, tenant_id: str) -> str:
        tenant_id = require_tenant_id(tenant_id, method="begin_document_replacement")
        async with self.async_session() as session:
            async with session.begin():
                # Row lock serialises concurrent replace requests: exactly one
                # caller observes "started", the rest see "in_progress".
                result = await session.execute(
                    select(Document)
                    .where(
                        Document.id == doc_id,
                        Document.tenant_id == tenant_id,
                    )
                    .with_for_update()
                )
                document = result.scalar_one_or_none()
                if document is None:
                    return "not_found"
                if document.status_detail == REPLACEMENT_IN_PROGRESS:
                    return "in_progress"
                if document.status not in _REPLACEABLE_STATUSES:
                    return "not_eligible"

                document.status_detail = REPLACEMENT_IN_PROGRESS
                if document.status == "completed":
                    # Drop any stale replacement_failed error; a failed document
                    # keeps the error that explains why it has no content.
                    document.error = None
                document.updated_at = datetime.utcnow()
            logger.info(f"[PostgreSQL] Began replacement for document {doc_id}")
            return "started"

    async def set_document_status_detail(
        self,
        doc_id: str,
        status_detail: Optional[str],
        tenant_id: str,
        *,
        error: dict | None = None,
        job_metadata_patch: dict | None = None,
    ) -> None:
        tenant_id = require_tenant_id(tenant_id, method="set_document_status_detail")
        async with self.async_session() as session:
            result = await session.execute(
                select(Document).where(
                    Document.id == doc_id,
                    Document.tenant_id == tenant_id,
                )
            )
            document = result.scalar_one_or_none()
            if not document:
                logger.warning(
                    "[PostgreSQL] set_document_status_detail: document %s not found for tenant %s",
                    doc_id,
                    tenant_id,
                )
                return

            document.status_detail = status_detail
            if error is not None:
                document.error = _replacement_error_preserving_prior(
                    document.status,
                    document.error,
                    status_detail,
                    error,
                )
            _apply_job_metadata_patch(document, job_metadata_patch)
            document.updated_at = datetime.utcnow()
            await session.commit()
            logger.debug(f"[PostgreSQL] Set status_detail for {doc_id} -> {status_detail}")

    async def replace_document_content(
        self,
        doc_id: str,
        chunk_records: list[ChunkRecord],
        tenant_id: str,
        *,
        file_name: str,
        metadata: dict | None = None,
    ) -> list[str]:
        tenant_id = require_tenant_id(tenant_id, method="replace_document_content")
        async with self.async_session() as session:
            async with session.begin():
                result = await session.execute(
                    select(Document)
                    .where(
                        Document.id == doc_id,
                        Document.tenant_id == tenant_id,
                    )
                    .with_for_update()
                )
                document = result.scalar_one_or_none()
                if document is None:
                    raise ValueError(
                        f"replace_document_content: document {doc_id} not found for tenant {tenant_id}"
                    )

                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                )

                chunk_ids: list[str] = []
                for record in chunk_records:
                    chunk_id = str(uuid.uuid4())
                    chunk_ids.append(chunk_id)
                    session.add(
                        DocumentChunk(
                            id=chunk_id,
                            document_id=doc_id,
                            chunk_text=record.chunk_text,
                            embedding=record.embedding,
                            chunk_index=record.chunk_index,
                            page_number=record.page_number,
                            character_offset_start=record.character_offset_start,
                            character_offset_end=record.character_offset_end,
                        )
                    )

                document.file_name = file_name
                if metadata is not None:
                    document.doc_metadata = metadata
                document.status = "completed"
                document.status_detail = None
                document.error = None
                document.chunks = {
                    "total": len(chunk_records),
                    "processed": len(chunk_records),
                }
                document.updated_at = datetime.utcnow()

            logger.info(
                "[PostgreSQL] Replaced content for document %s (%s chunks)",
                doc_id,
                len(chunk_ids),
            )
            return chunk_ids

    async def delete_document_chunks(self, doc_id: str, tenant_id: str) -> None:
        tenant_id = require_tenant_id(tenant_id, method="delete_document_chunks")
        async with self.async_session() as session:
            if not await self._document_owned_by_tenant(session, doc_id, tenant_id):
                logger.warning(
                    "[PostgreSQL] delete_document_chunks: document %s not found for tenant %s",
                    doc_id,
                    tenant_id,
                )
                return
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
            await session.commit()
            logger.info(f"[PostgreSQL] Deleted chunks for document {doc_id}")

    async def delete_document(self, document_id: str, tenant_id: str) -> None:
        tenant_id = require_tenant_id(tenant_id, method="delete_document")
        async with self.async_session() as session:
            try:
                async with session.begin():
                    result = await session.execute(
                        select(Document).where(
                            Document.id == document_id,
                            Document.tenant_id == tenant_id,
                        )
                    )
                    document = result.scalar_one_or_none()
                    if not document:
                        logger.warning(
                            "[PostgreSQL] delete_document: document %s not found for tenant %s",
                            document_id,
                            tenant_id,
                        )
                        return

                    await session.execute(
                        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                    )
                    await session.execute(
                        delete(SessionDocument).where(
                            SessionDocument.document_id == document_id
                        )
                    )
                    await session.execute(
                        delete(Document).where(
                            Document.id == document_id,
                            Document.tenant_id == tenant_id,
                        )
                    )
                logger.info(f"[PostgreSQL] Atomically deleted document {document_id}")
            except Exception:
                logger.error(f"[PostgreSQL] Failed to delete document {document_id}")
                raise

    async def fail_stale_documents_global(self, statuses: list[str]) -> set[str]:
        async with self.async_session() as session:
            rows = await session.execute(
                select(Document.id).where(Document.status.in_(statuses))
            )
            doc_ids = {str(row[0]) for row in rows}

            if doc_ids:
                await session.execute(
                    sql_update(Document)
                    .where(
                        Document.id.in_(doc_ids),
                        Document.status.in_(statuses),
                    )
                    .values(
                        status="failed",
                        error={
                            "stage": "server_restart",
                            "message": "Server restarted while document was being processed.",
                        },
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()

            logger.info(f"[PostgreSQL] Marked {len(doc_ids)} stale document(s) as failed on startup")

            # An in-flight replacement cannot survive a restart. Leave `status` and
            # the active chunks alone so the prior content stays retrievable, and
            # clear the in-progress marker so the document can be replaced again.
            replacement_rows = await session.execute(
                select(Document.id, Document.status, Document.error).where(
                    Document.status_detail == REPLACEMENT_IN_PROGRESS
                )
            )
            replacement_ids: set[str] = set()
            restart_error = {
                "stage": "server_restart",
                "code": "server_restart",
                "message": (
                    "Server restarted while document replacement was being processed."
                ),
            }
            for row in replacement_rows:
                replacement_id = str(row[0])
                replacement_ids.add(replacement_id)
                await session.execute(
                    sql_update(Document)
                    .where(Document.id == replacement_id)
                    .values(
                        status_detail=REPLACEMENT_FAILED,
                        error=_replacement_error_preserving_prior(
                            row[1],
                            row[2],
                            REPLACEMENT_FAILED,
                            restart_error,
                        ),
                        updated_at=datetime.utcnow(),
                    )
                )
            if replacement_ids:
                await session.commit()
                logger.info(
                    f"[PostgreSQL] Reset {len(replacement_ids)} stale replacement(s) on startup"
                )
            return doc_ids | replacement_ids

    def _chunk_match_from_row(
        self,
        chunk: DocumentChunk,
        file_name: str,
        *,
        similarity: float | None = None,
        score_type: str | None = None,
        vector_score: float | None = None,
        full_text_score: float | None = None,
    ) -> ChunkMatch:
        return ChunkMatch(
            id=str(chunk.id),
            chunk_text=chunk.chunk_text,
            document_id=str(chunk.document_id),
            embedding=chunk.embedding,
            created_at=str(chunk.created_at) if chunk.created_at else None,
            similarity=similarity,
            score_type=score_type,
            vector_score=vector_score,
            full_text_score=full_text_score,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
            character_offset_start=chunk.character_offset_start,
            character_offset_end=chunk.character_offset_end,
            file_name=file_name,
        )

    @staticmethod
    def _merge_hybrid_match(
        existing: ChunkMatch | None,
        incoming: ChunkMatch,
    ) -> ChunkMatch:
        """Combine vector and keyword matches for the same chunk ID."""
        if existing is None:
            return incoming
        return ChunkMatch(
            id=existing.id,
            chunk_text=existing.chunk_text,
            document_id=existing.document_id,
            embedding=existing.embedding,
            created_at=existing.created_at,
            similarity=existing.similarity,
            score_type=existing.score_type,
            vector_score=(
                existing.vector_score
                if existing.vector_score is not None
                else incoming.vector_score
            ),
            full_text_score=(
                existing.full_text_score
                if existing.full_text_score is not None
                else incoming.full_text_score
            ),
            chunk_index=existing.chunk_index,
            page_number=existing.page_number,
            character_offset_start=existing.character_offset_start,
            character_offset_end=existing.character_offset_end,
            file_name=existing.file_name,
        )

    async def _find_vector_chunks(
        self,
        session: AsyncSession,
        doc_id: str,
        query_embedding: list[float],
        limit: int,
        tenant_id: Optional[str] = None,
    ) -> list[ChunkMatch]:
        distance = DocumentChunk.embedding.op("<=>")(query_embedding)
        similarity_expr = (literal(1.0) - distance).label("similarity")
        stmt = (
            select(DocumentChunk, Document.file_name, similarity_expr)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(DocumentChunk.document_id == doc_id)
            .where(Document.status == "completed")
        )
        if tenant_id is not None:
            stmt = stmt.where(Document.tenant_id == tenant_id)
        stmt = stmt.order_by(distance).limit(limit)
        result = await session.execute(stmt)
        return [
            self._chunk_match_from_row(
                chunk,
                file_name,
                similarity=float(similarity) if similarity is not None else None,
                score_type=SCORE_TYPE_VECTOR,
                vector_score=float(similarity) if similarity is not None else None,
            )
            for chunk, file_name, similarity in result.all()
        ]

    async def _find_keyword_chunks(
        self,
        session: AsyncSession,
        doc_id: str,
        query_text: str,
        limit: int,
        tenant_id: Optional[str] = None,
    ) -> list[ChunkMatch]:
        """Full-text search on document_chunks.content_tsv (requires migration 004)."""
        content_tsv = literal_column("document_chunks.content_tsv", type_=TSVECTOR())
        ts_query = func.plainto_tsquery(_FTS_LANGUAGE, query_text)
        rank = func.ts_rank(content_tsv, ts_query).label("keyword_rank")
        try:
            stmt = (
                select(DocumentChunk, Document.file_name, rank)
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(DocumentChunk.document_id == doc_id)
                .where(Document.status == "completed")
                .where(content_tsv.op("@@")(ts_query))
            )
            if tenant_id is not None:
                stmt = stmt.where(Document.tenant_id == tenant_id)
            stmt = stmt.order_by(rank.desc()).limit(limit)
            result = await session.execute(stmt)
        except ProgrammingError as exc:
            if _is_missing_content_tsv_error(exc):
                logger.warning(
                    "content_tsv column missing; apply backend/db/init/004_hybrid_retrieval.sql. "
                    "Using vector-only results for this request."
                )
                return []
            raise
        rows = result.all()
        return [
            self._chunk_match_from_row(
                chunk,
                file_name,
                similarity=float(rank) if rank is not None else None,
                full_text_score=float(rank) if rank is not None else None,
            )
            for chunk, file_name, rank in rows
        ]

    async def _search_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int,
        *,
        session_id: Optional[str] = None,
        query_text: Optional[str] = None,
        tenant_id: Optional[str] = None,
        hybrid_enabled: Optional[bool] = None,
    ) -> list[ChunkMatch]:
        del session_id  # reserved for future session-scoped retrieval
        start = time.perf_counter()
        hybrid_flag = (
            config.HYBRID_RETRIEVAL_ENABLED if hybrid_enabled is None else hybrid_enabled
        )
        use_hybrid = bool(hybrid_flag) and bool(query_text and query_text.strip())
        candidate_limit = match_count * 2

        try:
            async with self._retrieval_semaphore:
                async with self.async_session() as session:
                    if not use_hybrid:
                        matches = await self._find_vector_chunks(
                            session, doc_id, query_embedding, match_count,
                            tenant_id=tenant_id,
                        )
                    else:
                        vector_matches = await self._find_vector_chunks(
                            session, doc_id, query_embedding, candidate_limit,
                            tenant_id=tenant_id,
                        )
                        keyword_matches = await self._find_keyword_chunks(
                            session, doc_id, query_text.strip(), candidate_limit,
                            tenant_id=tenant_id,
                        )
                        matches_by_id: dict[str, ChunkMatch] = {}
                        for match in vector_matches:
                            matches_by_id[match.id] = match
                        for match in keyword_matches:
                            matches_by_id[match.id] = self._merge_hybrid_match(
                                matches_by_id.get(match.id),
                                match,
                            )

                        rrf_scores = reciprocal_rank_fusion_scores(
                            [
                                [m.id for m in vector_matches],
                                [m.id for m in keyword_matches],
                            ],
                            limit=match_count,
                        )
                        fused_ids = list(rrf_scores.keys())
                        matches = merge_chunk_matches_with_scores(
                            fused_ids,
                            matches_by_id,
                            rrf_scores,
                            score_type=SCORE_TYPE_HYBRID_RRF,
                        )

                    duration_ms = int((time.perf_counter() - start) * 1000)
                    mode = "hybrid" if use_hybrid else "vector"
                    logger.debug(
                        "[PostgreSQL] %s search returned %s chunks for doc_id=%s in %sms",
                        mode,
                        len(matches),
                        doc_id,
                        duration_ms,
                    )
                    return matches
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "[PostgreSQL] Chunk search failed for doc_id=%s in %sms",
                doc_id,
                duration_ms,
            )
            raise

    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int,
        *,
        tenant_id: str,
        session_id: Optional[str] = None,
        query_text: Optional[str] = None,
        hybrid_enabled: Optional[bool] = None,
    ) -> list[ChunkMatch]:
        tenant_id = require_tenant_id(tenant_id, method="find_similar_chunks")
        return await self._search_similar_chunks(
            doc_id,
            query_embedding,
            match_count,
            session_id=session_id,
            query_text=query_text,
            tenant_id=tenant_id,
            hybrid_enabled=hybrid_enabled,
        )

    async def list_tenant_documents(self, tenant_id: str) -> list[str]:
        tenant_id = require_tenant_id(tenant_id, method="list_tenant_documents")
        async with self.async_session() as session:
            rows = await session.execute(
                select(Document.id)
                .where(Document.tenant_id == tenant_id)
                .order_by(Document.created_at)
            )
            return [str(row[0]) for row in rows]

    async def filter_document_ids_by_metadata(
        self, tenant_id: str, doc_ids: list[str], metadata_filter: dict
    ) -> list[str]:
        tenant_id = require_tenant_id(tenant_id, method="filter_document_ids_by_metadata")
        candidate_ids: dict[str, uuid.UUID] = {}
        for doc_id in doc_ids:
            try:
                candidate_ids[doc_id] = uuid.UUID(str(doc_id))
            except ValueError:
                continue  # not a document ID, so it cannot match
        if not candidate_ids:
            return []

        # JSONB containment (@>) is same-type and uses idx_documents_metadata_gin.
        conditions = [
            Document.tenant_id == tenant_id,
            Document.id.in_(set(candidate_ids.values())),
        ]
        for key, operand in metadata_filter.items():
            if isinstance(operand, dict):
                conditions.append(
                    or_(*[Document.doc_metadata.contains({key: value}) for value in operand["in"]])
                )
            else:
                conditions.append(Document.doc_metadata.contains({key: operand}))

        async with self.async_session() as session:
            rows = await session.execute(select(Document.id).where(and_(*conditions)))
            matched = {row[0] for row in rows}
        return [doc_id for doc_id, doc_uuid in candidate_ids.items() if doc_uuid in matched]

    async def list_tenant_document_summaries(self, tenant_id: str) -> list[dict]:
        tenant_id = require_tenant_id(tenant_id, method="list_tenant_document_summaries")
        async with self.async_session() as session:
            result = await session.execute(
                select(Document)
                .where(Document.tenant_id == tenant_id)
                .order_by(Document.created_at.desc())
            )
            summaries = []
            for document in result.scalars().all():
                summary = {
                    "document_id": str(document.id),
                    "file_name": document.file_name,
                    "status": document.status,
                    "metadata": document.doc_metadata or {},
                    "created_at": str(document.created_at) if document.created_at else None,
                    "updated_at": str(document.updated_at) if document.updated_at else None,
                }
                if document.status_detail is not None:
                    summary["status_detail"] = document.status_detail
                summaries.append(summary)
            return summaries

    async def ping_and_count_tenant_documents(
        self, tenant_id: str
    ) -> tuple[bool, int | None]:
        tenant_id = require_tenant_id(
            tenant_id, method="ping_and_count_tenant_documents"
        )
        try:
            async with self.async_session() as session:
                await session.execute(text("SELECT 1"))
                count = await session.scalar(
                    select(func.count())
                    .select_from(Document)
                    .where(Document.tenant_id == tenant_id)
                )
            return True, int(count or 0)
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("Database health check failed: %s", exc)
            return False, None
        except Exception:
            logger.exception("Unexpected error during database health check")
            return False, None

    async def store_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tenant_id: str,
    ) -> str:
        tenant_id = require_tenant_id(tenant_id, method="store_chat_message")
        async with self.async_session() as session:
            from core.models import ChatMessage
            msg_id = str(uuid.uuid4())
            msg = ChatMessage(
                id=msg_id,
                session_id=session_id,
                tenant_id=tenant_id,
                role=role,
                content=content,
            )
            session.add(msg)
            await session.commit()
            logger.debug(f"[PostgreSQL] Stored chat message {msg_id} for session {session_id}")
            return msg_id

    async def store_chat_turn(
        self,
        session_id: str,
        question: str,
        answer: str,
        tenant_id: str,
        *,
        sources: Optional[list] = None,
    ) -> tuple[str, str]:
        tenant_id = require_tenant_id(tenant_id, method="store_chat_turn")
        assistant_sources = copy.deepcopy(sources) if sources is not None else None
        async with self.async_session() as session:
            from core.models import ChatMessage

            user_msg_id = str(uuid.uuid4())
            assistant_msg_id = str(uuid.uuid4())
            async with session.begin():
                session.add(
                    ChatMessage(
                        id=user_msg_id,
                        session_id=session_id,
                        tenant_id=tenant_id,
                        role="user",
                        content=question,
                    )
                )
                session.add(
                    ChatMessage(
                        id=assistant_msg_id,
                        session_id=session_id,
                        tenant_id=tenant_id,
                        role="assistant",
                        content=answer,
                        sources=assistant_sources,
                    )
                )
            logger.debug(
                "[PostgreSQL] Stored chat turn for session %s (user=%s, assistant=%s)",
                session_id,
                user_msg_id,
                assistant_msg_id,
            )
            return user_msg_id, assistant_msg_id

    async def get_session_history(
        self,
        session_id: str,
        tenant_id: str,
        *,
        limit: int = 20,
    ) -> list[dict]:
        tenant_id = require_tenant_id(tenant_id, method="get_session_history")
        async with self.async_session() as session:
            from core.models import ChatMessage
            stmt = (
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == session_id,
                    ChatMessage.tenant_id == tenant_id,
                )
                .order_by(
                    ChatMessage.created_at.desc(),
                    ChatMessage.id.desc(),
                )
                .limit(limit)
            )

            result = await session.execute(stmt)
            messages = result.scalars().all()

            return [
                {
                    "id": str(msg.id),
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": str(msg.created_at) if msg.created_at else None,
                    "sources": msg.sources,
                }
                for msg in reversed(messages)
            ]

    # ── Session persistence ──────────────────────────────────────────────────

    def _session_from_record(
        self,
        record: SessionRecord,
        document_ids: list[str],
        display_label: str = NEW_SESSION_LABEL,
    ) -> Session:
        from datetime import timezone

        def _to_aware(dt: datetime | None) -> datetime:
            if dt is None:
                return datetime.now(timezone.utc)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

        return Session(
            id=record.id,
            tenant_id=record.tenant_id,
            created_at=_to_aware(record.created_at),
            last_active=_to_aware(record.last_active),
            document_ids=document_ids,
            display_label=display_label,
        )

    async def _load_session_document_ids(
        self, db_session: AsyncSession, session_id: str
    ) -> list[str]:
        result = await db_session.execute(
            select(SessionDocument.document_id).where(
                SessionDocument.session_id == session_id
            )
        )
        return [row[0] for row in result.all()]

    async def create_session_record(
        self, session_id: str, tenant_id: Optional[str]
    ) -> Session:
        async with self.async_session() as db_session:
            record = SessionRecord(id=session_id, tenant_id=tenant_id)
            db_session.add(record)
            await db_session.commit()
            await db_session.refresh(record)
            logger.info(f"[PostgreSQL] Created session {session_id} (tenant={tenant_id})")
            return self._session_from_record(record, [])

    async def get_or_create_session_record(
        self, session_id: str, tenant_id: Optional[str]
    ) -> Optional[Session]:
        async with self.async_session() as db_session:
            stmt = (
                insert(SessionRecord)
                .values(id=session_id, tenant_id=tenant_id)
                .on_conflict_do_nothing(index_elements=["id"])
            )
            await db_session.execute(stmt)
            await db_session.commit()

            result = await db_session.execute(
                select(SessionRecord).where(SessionRecord.id == session_id)
            )
            record = result.scalar_one()
            if tenant_id is not None and record.tenant_id is not None and record.tenant_id != tenant_id:
                logger.warning(
                    "get_or_create_session_record: tenant mismatch for session %s",
                    session_id,
                )
                return None
            doc_ids = await self._load_session_document_ids(db_session, session_id)
            labels = await self._load_display_labels(db_session, [session_id])
            return self._session_from_record(
                record,
                doc_ids,
                labels.get(session_id, NEW_SESSION_LABEL),
            )

    async def get_session_record(
        self, session_id: str, tenant_id: Optional[str]
    ) -> Optional[Session]:
        async with self.async_session() as db_session:
            result = await db_session.execute(
                select(SessionRecord).where(SessionRecord.id == session_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            if tenant_id is not None and record.tenant_id is not None and record.tenant_id != tenant_id:
                logger.warning(
                    f"Session {session_id} tenant mismatch: {record.tenant_id} vs {tenant_id}"
                )
                return None
            # Touch last_active
            await db_session.execute(
                sql_update(SessionRecord)
                .where(SessionRecord.id == session_id)
                .values(last_active=datetime.utcnow())
            )
            await db_session.commit()
            await db_session.refresh(record)
            doc_ids = await self._load_session_document_ids(db_session, session_id)
            labels = await self._load_display_labels(db_session, [session_id])
            return self._session_from_record(
                record,
                doc_ids,
                labels.get(session_id, NEW_SESSION_LABEL),
            )

    async def _load_display_labels(
        self, db_session: AsyncSession, session_ids: list[str]
    ) -> dict[str, str]:
        """Compute display labels for a set of sessions in two queries.

        The first query picks the earliest useful user message per session.
        The second picks one attached file name per session. Neither loops
        over sessions.
        """
        if not session_ids:
            return {}

        useful_content = func.regexp_replace(
            ChatMessage.content, "[[:space:]]", "", "g"
        )
        question_rank = func.row_number().over(
            partition_by=ChatMessage.session_id,
            order_by=(ChatMessage.created_at.asc(), ChatMessage.id.asc()),
        )
        question_rows = (
            select(
                ChatMessage.session_id.label("session_id"),
                ChatMessage.content.label("content"),
                question_rank.label("rn"),
            )
            .where(
                ChatMessage.session_id.in_(session_ids),
                ChatMessage.role == "user",
                useful_content != "",
            )
            .subquery()
        )
        question_result = await db_session.execute(
            select(question_rows.c.session_id, question_rows.c.content).where(
                question_rows.c.rn == 1
            )
        )
        questions: dict[str, str] = {}
        for session_id, content in question_result.all():
            collapsed = " ".join((content or "").split())
            if collapsed:
                questions[session_id] = collapsed

        doc_id_text = cast(Document.id, String)
        useful_file_name = func.regexp_replace(
            Document.file_name, "[[:space:]]", "", "g"
        )
        file_rank = func.row_number().over(
            partition_by=SessionDocument.session_id,
            order_by=(Document.created_at.desc(), doc_id_text.asc()),
        )
        file_rows = (
            select(
                SessionDocument.session_id.label("session_id"),
                Document.file_name.label("file_name"),
                file_rank.label("rn"),
            )
            .join(Document, doc_id_text == SessionDocument.document_id)
            .where(
                SessionDocument.session_id.in_(session_ids),
                useful_file_name != "",
            )
            .subquery()
        )
        file_result = await db_session.execute(
            select(file_rows.c.session_id, file_rows.c.file_name).where(
                file_rows.c.rn == 1
            )
        )
        file_names: dict[str, str] = {}
        for session_id, file_name in file_result.all():
            cleaned = (file_name or "").strip()
            if cleaned:
                file_names[session_id] = cleaned

        return {
            session_id: questions.get(session_id)
            or file_names.get(session_id)
            or NEW_SESSION_LABEL
            for session_id in session_ids
        }

    async def list_session_records(self, tenant_id: Optional[str]) -> list[Session]:
        async with self.async_session() as db_session:
            stmt = select(SessionRecord).order_by(
                SessionRecord.last_active.desc(),
                SessionRecord.id.desc(),
            )
            if tenant_id is not None:
                stmt = stmt.where(SessionRecord.tenant_id == tenant_id)
            result = await db_session.execute(stmt)
            records = result.scalars().all()
            if not records:
                return []

            session_ids = [record.id for record in records]
            doc_result = await db_session.execute(
                select(SessionDocument.session_id, SessionDocument.document_id).where(
                    SessionDocument.session_id.in_(session_ids)
                )
            )
            docs_by_session: dict[str, list[str]] = defaultdict(list)
            for session_id, document_id in doc_result.all():
                docs_by_session[session_id].append(document_id)

            labels = await self._load_display_labels(db_session, session_ids)
            return [
                self._session_from_record(
                    record,
                    docs_by_session.get(record.id, []),
                    labels.get(record.id, NEW_SESSION_LABEL),
                )
                for record in records
            ]

    async def delete_session_record(
        self, session_id: str, tenant_id: Optional[str]
    ) -> bool:
        async with self.async_session() as db_session:
            from core.models import ChatMessage

            async with db_session.begin():
                result = await db_session.execute(
                    select(SessionRecord).where(SessionRecord.id == session_id)
                )
                record = result.scalar_one_or_none()
                if record is None:
                    return False
                if (
                    tenant_id is not None
                    and record.tenant_id is not None
                    and record.tenant_id != tenant_id
                ):
                    logger.warning(
                        f"delete_session_record: tenant mismatch for session {session_id}"
                    )
                    return False
                await db_session.execute(
                    delete(ChatMessage).where(
                        ChatMessage.session_id == session_id,
                        ChatMessage.tenant_id == record.tenant_id,
                    )
                )
                await db_session.execute(
                    delete(SessionRecord).where(SessionRecord.id == session_id)
                )
            logger.info(f"[PostgreSQL] Deleted session {session_id}")
            return True

    async def add_session_document(self, session_id: str, document_id: str) -> None:
        async with self.async_session() as db_session:
            stmt = (
                insert(SessionDocument)
                .values(session_id=session_id, document_id=document_id)
                .on_conflict_do_nothing(
                    index_elements=["session_id", "document_id"]
                )
            )
            await db_session.execute(stmt)
            await db_session.commit()
            logger.debug(
                f"[PostgreSQL] Bound document {document_id} to session {session_id}"
            )

    async def get_chat_message(self, message_id: str, tenant_id: str) -> dict | None:
        tenant_id = require_tenant_id(tenant_id, method="get_chat_message")
        from uuid import UUID

        from core.models import ChatMessage

        try:
            msg_uuid = UUID(message_id)
        except ValueError:
            return None

        async with self.async_session() as session:
            result = await session.execute(
                select(ChatMessage).where(
                    ChatMessage.id == msg_uuid,
                    ChatMessage.tenant_id == tenant_id,
                )
            )
            message = result.scalar_one_or_none()
            if message is None:
                return None
            return {
                "id": str(message.id),
                "session_id": message.session_id,
                "tenant_id": message.tenant_id,
                "role": message.role,
                "content": message.content,
            }

    def _feedback_row(self, record) -> dict:
        from core.models import RetrievalFeedback

        assert isinstance(record, RetrievalFeedback)
        return {
            "id": str(record.id),
            "type": record.feedback_type,
            "rating": record.rating,
            "comment": record.comment,
            "session_id": record.session_id,
            "message_id": str(record.message_id) if record.message_id else None,
            "document_id": str(record.document_id) if record.document_id else None,
            "chunk_index": record.chunk_index,
            "created_at": record.created_at.isoformat() if record.created_at else "",
        }

    async def create_retrieval_feedback(
        self,
        *,
        tenant_id: str,
        session_id: str,
        feedback_type: str,
        rating: int,
        comment: str | None,
        message_id: str | None,
        document_id: str | None,
        chunk_index: int | None,
    ) -> dict:
        tenant_id = require_tenant_id(tenant_id, method="create_retrieval_feedback")
        from uuid import UUID

        from core.models import RetrievalFeedback

        async with self.async_session() as session:
            record = RetrievalFeedback(
                tenant_id=tenant_id,
                session_id=session_id,
                feedback_type=feedback_type,
                rating=rating,
                comment=comment,
                message_id=UUID(message_id) if message_id else None,
                document_id=UUID(document_id) if document_id else None,
                chunk_index=chunk_index,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return self._feedback_row(record)

    async def list_retrieval_feedback(
        self,
        *,
        tenant_id: str,
        session_id: str | None = None,
        created_after=None,
        created_before=None,
        limit: int = 50,
    ) -> list[dict]:
        tenant_id = require_tenant_id(tenant_id, method="list_retrieval_feedback")
        from core.models import RetrievalFeedback

        async with self.async_session() as session:
            stmt = select(RetrievalFeedback).where(
                RetrievalFeedback.tenant_id == tenant_id
            )
            if session_id is not None:
                stmt = stmt.where(RetrievalFeedback.session_id == session_id)
            if created_after is not None:
                stmt = stmt.where(RetrievalFeedback.created_at >= created_after)
            if created_before is not None:
                stmt = stmt.where(RetrievalFeedback.created_at <= created_before)
            stmt = stmt.order_by(
                RetrievalFeedback.created_at.desc(),
                RetrievalFeedback.id.desc(),
            ).limit(limit)

            result = await session.execute(stmt)
            return [self._feedback_row(row) for row in result.scalars().all()]

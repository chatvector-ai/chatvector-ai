import logging
import os
import asyncio
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    delete,
    func,
    literal,
    literal_column,
    select,
    text,
    update as sql_update,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.models import Document, DocumentChunk, SessionRecord, SessionDocument
from core.config import config
from core.session import Session
from db.base import ChunkMatch, ChunkRecord, DatabaseService
from db.migration_ledger import MigrationLedgerSchemaError
from db.tenant_scope import require_tenant_id
from services.retrieval_service import (
    SCORE_TYPE_HYBRID_RRF,
    SCORE_TYPE_VECTOR,
    merge_chunk_matches_with_scores,
    reciprocal_rank_fusion,
    reciprocal_rank_fusion_scores,
)

logger = logging.getLogger(__name__)

# Full-text config matches migration 004 (to_tsvector / plainto_tsquery).
_FTS_LANGUAGE = "english"


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
        "created_at": str(document.created_at) if document.created_at else None,
        "updated_at": str(document.updated_at) if document.updated_at else None,
    }


def _document_status_payload(document: Document) -> dict:
    return {
        "document_id": str(document.id),
        "status": document.status,
        "chunks": document.chunks,
        "error": document.error,
        "created_at": str(document.created_at) if document.created_at else None,
        "updated_at": str(document.updated_at) if document.updated_at else None,
    }


class SQLAlchemyService(DatabaseService):
    """
    Development database service using PostgreSQL with pgvector.
    """

    def __init__(self):
        db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
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

    async def create_document(self, filename: str, tenant_id: str) -> str:
        tenant_id = require_tenant_id(tenant_id, method="create_document")
        async with self.async_session() as session:
            doc_id = str(uuid.uuid4())
            document = Document(
                id=doc_id,
                file_name=filename,
                tenant_id=tenant_id,
                status="uploaded",
                chunks={"total": 0, "processed": 0},
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
            if not await self._document_owned_by_tenant(session, doc_id, tenant_id):
                raise ValueError(
                    f"store_chunks_with_embeddings: document {doc_id} not found for tenant {tenant_id}"
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
            await session.commit()

            logger.info(f"[PostgreSQL] Inserted {len(chunk_ids)} chunks for document {doc_id}")
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
            if chunks is not None:
                document.chunks = chunks
            document.updated_at = datetime.utcnow()

            await session.commit()
            logger.debug(f"[PostgreSQL] Updated status for {doc_id} -> {status}")

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
                    .where(Document.id.in_(doc_ids))
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
            return doc_ids

    def _chunk_match_from_row(
        self,
        chunk: DocumentChunk,
        file_name: str,
        *,
        similarity: float | None = None,
        score_type: str | None = None,
    ) -> ChunkMatch:
        return ChunkMatch(
            id=str(chunk.id),
            chunk_text=chunk.chunk_text,
            document_id=str(chunk.document_id),
            embedding=chunk.embedding,
            created_at=str(chunk.created_at) if chunk.created_at else None,
            similarity=similarity,
            score_type=score_type,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
            character_offset_start=chunk.character_offset_start,
            character_offset_end=chunk.character_offset_end,
            file_name=file_name,
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
            self._chunk_match_from_row(chunk, file_name)
            for chunk, file_name, _rank in rows
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
    ) -> list[ChunkMatch]:
        del session_id  # reserved for future session-scoped retrieval
        start = time.perf_counter()
        use_hybrid = (
            config.HYBRID_RETRIEVAL_ENABLED
            and query_text
            and query_text.strip()
        )
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
                        for match in vector_matches + keyword_matches:
                            matches_by_id[match.id] = match

                        fused_ids = reciprocal_rank_fusion(
                            [
                                [m.id for m in vector_matches],
                                [m.id for m in keyword_matches],
                            ],
                            limit=match_count,
                        )
                        rrf_scores = reciprocal_rank_fusion_scores(
                            [
                                [m.id for m in vector_matches],
                                [m.id for m in keyword_matches],
                            ],
                            limit=match_count,
                        )
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
    ) -> list[ChunkMatch]:
        tenant_id = require_tenant_id(tenant_id, method="find_similar_chunks")
        return await self._search_similar_chunks(
            doc_id,
            query_embedding,
            match_count,
            session_id=session_id,
            query_text=query_text,
            tenant_id=tenant_id,
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
                .order_by(ChatMessage.created_at.desc())
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
                }
                for msg in reversed(messages)
            ]

    # ── Session persistence ──────────────────────────────────────────────────

    def _session_from_record(
        self, record: SessionRecord, document_ids: list[str]
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
            if tenant_id and record.tenant_id and record.tenant_id != tenant_id:
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
            return self._session_from_record(record, doc_ids)

    async def list_session_records(self, tenant_id: Optional[str]) -> list[Session]:
        async with self.async_session() as db_session:
            stmt = select(SessionRecord)
            if tenant_id:
                stmt = stmt.where(SessionRecord.tenant_id == tenant_id)
            result = await db_session.execute(stmt)
            records = result.scalars().all()
            sessions = []
            for record in records:
                doc_ids = await self._load_session_document_ids(db_session, record.id)
                sessions.append(self._session_from_record(record, doc_ids))
            return sessions

    async def delete_session_record(
        self, session_id: str, tenant_id: Optional[str]
    ) -> bool:
        async with self.async_session() as db_session:
            result = await db_session.execute(
                select(SessionRecord).where(SessionRecord.id == session_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return False
            if tenant_id and record.tenant_id and record.tenant_id != tenant_id:
                logger.warning(
                    f"delete_session_record: tenant mismatch for session {session_id}"
                )
                return False
            await db_session.execute(
                delete(SessionRecord).where(SessionRecord.id == session_id)
            )
            await db_session.commit()
            logger.info(f"[PostgreSQL] Deleted session {session_id}")
            return True

    async def add_session_document(self, session_id: str, document_id: str) -> None:
        async with self.async_session() as db_session:
            existing = await db_session.execute(
                select(SessionDocument).where(
                    SessionDocument.session_id == session_id,
                    SessionDocument.document_id == document_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                return
            db_session.add(
                SessionDocument(session_id=session_id, document_id=document_id)
            )
            await db_session.commit()
            logger.debug(
                f"[PostgreSQL] Bound document {document_id} to session {session_id}"
            )

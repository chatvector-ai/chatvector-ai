import logging
import os
import asyncio
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, literal, literal_column, select, update as sql_update
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.models import Document, DocumentChunk
from core.config import config
from db.base import ChunkMatch, ChunkRecord, DatabaseService
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

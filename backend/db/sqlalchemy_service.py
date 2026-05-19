import logging
import os
import asyncio
import time
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select, text, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.models import Document, DocumentChunk
from core.config import config
from db.base import ChunkMatch, ChunkRecord, DatabaseService
from services.retrieval_service import merge_chunk_matches, reciprocal_rank_fusion

logger = logging.getLogger(__name__)


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

    async def create_document(self, filename: str, tenant_id: Optional[str] = None) -> str:
        async with self.async_session() as session:
            doc_id = str(uuid.uuid4())
            document = Document(
                id=doc_id,
                file_name=filename,
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
        tenant_id: Optional[str] = None,
    ) -> list[str]:
        async with self.async_session() as session:
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

    async def get_document(self, doc_id: str, tenant_id: Optional[str] = None) -> dict | None:
        async with self.async_session() as session:
            document = await session.get(Document, doc_id)
            if not document:
                return None
            return {
                "id": str(document.id),
                "file_name": document.file_name,
                "status": document.status,
                "chunks": document.chunks,
                "error": document.error,
                "created_at": str(document.created_at) if document.created_at else None,
                "updated_at": str(document.updated_at) if document.updated_at else None,
            }

    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunk_records: list[ChunkRecord],
        tenant_id: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Atomic document+chunk creation with transaction."""
        async with self.async_session() as session:
            chunk_ids: list[str] = []
            doc_id = str(uuid.uuid4())

            try:
                async with session.begin():
                    document = Document(
                        id=doc_id,
                        file_name=file_name,
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
        error: dict | None = None,
        chunks: dict | None = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        async with self.async_session() as session:
            document = await session.get(Document, doc_id)
            if not document:
                logger.warning(
                    "[PostgreSQL] update_document_status: document %s not found, skipping",
                    doc_id,
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

    async def get_document_status(self, doc_id: str, tenant_id: Optional[str] = None) -> dict | None:
        async with self.async_session() as session:
            document = await session.get(Document, doc_id)
            if not document:
                return None

            return {
                "document_id": str(document.id),
                "status": document.status,
                "chunks": document.chunks,
                "error": document.error,
                "created_at": str(document.created_at) if document.created_at else None,
                "updated_at": str(document.updated_at) if document.updated_at else None,
            }

    async def delete_document_chunks(self, doc_id: str, tenant_id: Optional[str] = None) -> None:
        async with self.async_session() as session:
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
            await session.commit()
            logger.info(f"[PostgreSQL] Deleted chunks for failed upload document {doc_id}")

    async def delete_document(self, document_id: str, tenant_id: Optional[str] = None) -> None:
        async with self.async_session() as session:
            try:
                async with session.begin():
                    # Delete chunks first due to FK constraint
                    await session.execute(
                        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
                    )
                    await session.execute(
                        delete(Document).where(Document.id == document_id)
                    )
                logger.info(f"[PostgreSQL] Atomically deleted document {document_id}")
            except Exception:
                logger.error(f"[PostgreSQL] Failed to delete document {document_id}")
                raise

    async def fail_stale_documents(self, statuses: list[str], tenant_id: Optional[str] = None) -> set[str]:
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
                        error={"stage": "server_restart", "message": "Server restarted while document was being processed."},
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()

            logger.info(f"[PostgreSQL] Marked {len(doc_ids)} stale document(s) as failed on startup")
            return doc_ids

    def _chunk_match_from_row(
        self, chunk: DocumentChunk, file_name: str, *, similarity: float | None = None
    ) -> ChunkMatch:
        return ChunkMatch(
            id=str(chunk.id),
            chunk_text=chunk.chunk_text,
            document_id=str(chunk.document_id),
            embedding=chunk.embedding,
            created_at=str(chunk.created_at) if chunk.created_at else None,
            similarity=similarity,
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
    ) -> list[ChunkMatch]:
        result = await session.execute(
            select(DocumentChunk, Document.file_name)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.embedding.op("<=>")(query_embedding))
            .limit(limit)
        )
        return [
            self._chunk_match_from_row(chunk, file_name)
            for chunk, file_name in result.all()
        ]

    async def _find_keyword_chunks(
        self,
        session: AsyncSession,
        doc_id: str,
        query_text: str,
        limit: int,
    ) -> list[ChunkMatch]:
        """Full-text search on document_chunks.content_tsv (requires migration 004)."""
        rank = text(
            "ts_rank(document_chunks.content_tsv, plainto_tsquery('english', :query_text))"
        ).label("keyword_rank")
        result = await session.execute(
            select(DocumentChunk, Document.file_name, rank)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(DocumentChunk.document_id == doc_id)
            .where(
                text(
                    "document_chunks.content_tsv @@ plainto_tsquery('english', :query_text)"
                )
            )
            .order_by(rank.desc())
            .limit(limit),
            {"query_text": query_text},
        )
        rows = result.all()
        return [
            self._chunk_match_from_row(chunk, file_name)
            for chunk, file_name, _rank in rows
        ]

    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5,
        session_id: Optional[str] = None,
        query_text: Optional[str] = None,
    ) -> list[ChunkMatch]:
        # TODO(Phase 3): use session_id for context filtering once implemented
        """Find chunks via vector search; optionally fuse with PostgreSQL full-text search."""
        del session_id  # reserved for Phase 3 session-scoped retrieval
        start = time.perf_counter()
        use_hybrid = (
            config.HYBRID_RETRIEVAL_ENABLED
            and query_text
            and query_text.strip()
        )
        candidate_limit = max(match_count, match_count * 2)

        try:
            async with self._retrieval_semaphore:
                async with self.async_session() as session:
                    if not use_hybrid:
                        matches = await self._find_vector_chunks(
                            session, doc_id, query_embedding, match_count
                        )
                    else:
                        vector_matches, keyword_matches = await asyncio.gather(
                            self._find_vector_chunks(
                                session, doc_id, query_embedding, candidate_limit
                            ),
                            self._find_keyword_chunks(
                                session, doc_id, query_text.strip(), candidate_limit
                            ),
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
                        matches = merge_chunk_matches(fused_ids, matches_by_id)

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

    async def store_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tenant_id: Optional[str] = None,
    ) -> str:
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
        limit: int = 20,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        async with self.async_session() as session:
            from core.models import ChatMessage
            stmt = select(ChatMessage).where(ChatMessage.session_id == session_id)
            if tenant_id:
                stmt = stmt.where(ChatMessage.tenant_id == tenant_id)
            stmt = stmt.order_by(ChatMessage.created_at.desc()).limit(limit)
            
            result = await session.execute(stmt)
            messages = result.scalars().all()
            
            # Return ordered ascending (chronological)
            return [
                {
                    "id": str(msg.id),
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": str(msg.created_at) if msg.created_at else None,
                }
                for msg in reversed(messages)
            ]

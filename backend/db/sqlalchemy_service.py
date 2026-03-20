import logging
import os
import asyncio
import time
import uuid
from datetime import datetime

from sqlalchemy import delete, select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.models import Document, DocumentChunk
from core.config import config
from db.base import ChunkMatch, DatabaseService

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
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._retrieval_semaphore = asyncio.Semaphore(config.SQLALCHEMY_RETRIEVAL_CONCURRENCY)

    async def create_document(self, filename: str) -> str:
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
        chunks_with_embeddings: list[tuple[str, list[float]]],
    ) -> list[str]:
        async with self.async_session() as session:
            chunk_rows = []
            chunk_ids = []

            for chunk_text, embedding in chunks_with_embeddings:
                chunk_id = str(uuid.uuid4())
                chunk_ids.append(chunk_id)
                chunk_rows.append(
                    DocumentChunk(
                        id=chunk_id,
                        document_id=doc_id,
                        chunk_text=chunk_text,
                        embedding=embedding,
                    )
                )

            session.add_all(chunk_rows)
            await session.commit()

            logger.info(f"[PostgreSQL] Inserted {len(chunk_ids)} chunks for document {doc_id}")
            return chunk_ids

    async def get_document(self, doc_id: str) -> dict | None:
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
        chunks_with_embeddings: list[tuple[str, list[float]]],
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
                        chunks={"total": len(chunks_with_embeddings), "processed": len(chunks_with_embeddings)},
                    )
                    session.add(document)

                    for chunk_text, embedding in chunks_with_embeddings:
                        chunk_id = str(uuid.uuid4())
                        chunk_ids.append(chunk_id)
                        session.add(
                            DocumentChunk(
                                id=chunk_id,
                                document_id=doc_id,
                                chunk_text=chunk_text,
                                embedding=embedding,
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
    ) -> None:
        async with self.async_session() as session:
            document = await session.get(Document, doc_id)
            if not document:
                raise ValueError(f"Document {doc_id} not found")

            document.status = status
            if error is not None:
                document.error = error
            if chunks is not None:
                document.chunks = chunks
            document.updated_at = datetime.utcnow()

            await session.commit()
            logger.debug(f"[PostgreSQL] Updated status for {doc_id} -> {status}")

    async def get_document_status(self, doc_id: str) -> dict | None:
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

    async def delete_document_chunks(self, doc_id: str) -> None:
        async with self.async_session() as session:
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
            await session.commit()
            logger.info(f"[PostgreSQL] Deleted chunks for failed upload document {doc_id}")

    async def fail_stale_documents(self, statuses: list[str]) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                sql_update(Document)
                .where(Document.status.in_(statuses))
                .values(
                    status="failed",
                    error={"stage": "server_restart", "message": "Server restarted while document was being processed."},
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()
            count = result.rowcount
            logger.info(f"[PostgreSQL] Marked {count} stale document(s) as failed on startup")
            return count

    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5,
    ) -> list[ChunkMatch]:
        """Find similar chunks using pgvector."""
        start = time.perf_counter()
        try:
            async with self._retrieval_semaphore:
                async with self.async_session() as session:
                    result = await session.execute(
                        select(DocumentChunk)
                        .where(DocumentChunk.document_id == doc_id)
                        .order_by(DocumentChunk.embedding.op("<=>")(query_embedding))
                        .limit(match_count)
                    )
                    chunks = result.scalars().all()

                    matches = [
                        ChunkMatch(
                            id=str(chunk.id),
                            chunk_text=chunk.chunk_text,
                            document_id=str(chunk.document_id),
                            embedding=chunk.embedding,
                            created_at=str(chunk.created_at) if chunk.created_at else None,
                        )
                        for chunk in chunks
                    ]

                    duration_ms = int((time.perf_counter() - start) * 1000)
                    logger.debug(
                        "[PostgreSQL] Vector search returned %s chunks for doc_id=%s in %sms",
                        len(matches),
                        doc_id,
                        duration_ms,
                    )
                    return matches
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "[PostgreSQL] Vector search failed for doc_id=%s in %sms",
                doc_id,
                duration_ms,
            )
            raise

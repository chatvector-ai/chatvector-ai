import logging
import os
import uuid
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.models import Document, DocumentChunk
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
            pool_size=5,
            max_overflow=10,
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def create_document(self, filename: str) -> str:
        async with self.async_session() as session:
            doc_id = str(uuid.uuid4())
            document = Document(
                id=doc_id,
                file_name=filename,
                status="uploaded",
                chunks_total=0,
                chunks_processed=0,
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
                "failed_stage": document.failed_stage,
                "error_message": document.error_message,
                "chunks_total": document.chunks_total,
                "chunks_processed": document.chunks_processed,
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
                        chunks_total=len(chunks_with_embeddings),
                        chunks_processed=len(chunks_with_embeddings),
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
        failed_stage: str | None = None,
        error_message: str | None = None,
        chunks_total: int | None = None,
        chunks_processed: int | None = None,
    ) -> None:
        async with self.async_session() as session:
            document = await session.get(Document, doc_id)
            if not document:
                raise ValueError(f"Document {doc_id} not found")

            document.status = status
            if failed_stage is not None:
                document.failed_stage = failed_stage
            if error_message is not None:
                document.error_message = error_message
            if chunks_total is not None:
                document.chunks_total = chunks_total
            if chunks_processed is not None:
                document.chunks_processed = chunks_processed
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
                "failed_stage": document.failed_stage,
                "error_message": document.error_message,
                "chunks_total": document.chunks_total,
                "chunks_processed": document.chunks_processed,
                "created_at": str(document.created_at) if document.created_at else None,
                "updated_at": str(document.updated_at) if document.updated_at else None,
            }

    async def delete_document_chunks(self, doc_id: str) -> None:
        async with self.async_session() as session:
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
            await session.commit()
            logger.info(f"[PostgreSQL] Deleted chunks for failed upload document {doc_id}")

    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5,
    ) -> list[ChunkMatch]:
        """Find similar chunks using pgvector."""
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

            logger.debug(f"[PostgreSQL] Vector search returned {len(matches)} chunks")
            return matches

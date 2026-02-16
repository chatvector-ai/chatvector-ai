import uuid
import logging
from sqlalchemy.ext.asyncio import async_session
from sqlalchemy import select
from app.models import DocumentChunk, Document
from app.db.base import DatabaseService

logger = logging.getLogger(__name__)

# dev implementation - SQLAlchemy + SQLite/PostgreSQL
class SQLAlchemyService(DatabaseService):
    
    async def create_document(self, filename: str) -> str:
        async with async_session() as session:
            doc_id = str(uuid.uuid4())
            document = Document(
                id=doc_id,
                filename=filename,
                status="processing"  # You might want this
            )
            session.add(document)
            await session.commit()
            logger.info(f"[SQLAlchemy] Created document {doc_id}")
            return doc_id
    
    async def store_chunks_with_embeddings(
        self, 
        doc_id: str, 
        chunks_with_embeddings: list[tuple[str, list[float]]]
    ) -> list[str]:
        async with async_session() as session:
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
            
            logger.info(f"[SQLAlchemy] Inserted {len(chunk_ids)} chunks for document {doc_id}")
            return chunk_ids
    
    async def get_document(self, doc_id: str) -> dict:
        async with async_session() as session:
            document = await session.get(Document, doc_id)
            if document:
                return {
                    "id": document.id,
                    "filename": document.filename,
                    "status": document.status,
                    "created_at": document.created_at
                }
            return None
        
    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5
    ) -> list[DocumentChunk]:
        async with async_session() as session:
            result = await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc_id)
                .limit(match_count)
            )
            chunks = result.scalars().all()
            
            logger.debug(f"[SQLAlchemy] Found {len(chunks)} chunks for document {doc_id}")
            return chunks
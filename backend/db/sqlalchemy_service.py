import uuid
import logging
import os
from typing import List, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from core.models import DocumentChunk, Document
from db.base import DatabaseService

logger = logging.getLogger(__name__)

class SQLAlchemyService(DatabaseService):
    """
    Development database service using PostgreSQL with pgvector.
    Matches production Supabase environment for accurate testing.
    """
    
    def __init__(self):
        """Initialize PostgreSQL connection with asyncpg."""
        # Get database URL from environment or use default
        db_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
        # Convert to asyncpg format
        async_url = db_url.replace("postgresql://", "postgresql+asyncpg://")
        
        self.engine = create_async_engine(
            async_url,
            echo=False,  # Set to True for SQL debugging
            pool_size=5,
            max_overflow=10
        )
        self.async_session = sessionmaker(
            self.engine, 
            class_=AsyncSession, 
            expire_on_commit=False
        )
    
    # Create a document record.
    async def create_document(self, filename: str) -> str:
        async with self.async_session() as session:
            doc_id = str(uuid.uuid4())
            document = Document(
                id=doc_id,
                filename=filename,
                status="processing"
            )
            session.add(document)
            await session.commit()
            logger.info(f"[PostgreSQL] Created document {doc_id}")
            return doc_id
    
    # Store chunks with their vector embeddings.
    async def store_chunks_with_embeddings(
        self, 
        doc_id: str, 
        chunks_with_embeddings: List[Tuple[str, List[float]]]
    ) -> List[str]:
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
                        embedding=embedding,  # pgvector handles this automatically
                    )
                )
            
            session.add_all(chunk_rows)
            await session.commit()
            
            logger.info(f"[PostgreSQL] Inserted {len(chunk_ids)} chunks for document {doc_id}")
            return chunk_ids
    
    # Retrieve a document by ID
    async def get_document(self, doc_id: str) -> dict:
        async with self.async_session() as session:
            document = await session.get(Document, doc_id)
            if document:
                return {
                    "id": document.id,
                    "filename": document.filename,
                    "status": document.status,
                    "created_at": document.created_at
                }
            return None
    
    #Find chunks similar to query embedding using pgvector's cosine distance.Uses the <=> operator for cosine distance. 
    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: List[float],
        match_count: int = 5
    ) -> List[DocumentChunk]:
        async with self.async_session() as session:
            # Use pgvector's cosine distance operator
            result = await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc_id)
                .order_by(DocumentChunk.embedding.op("<=>")(query_embedding))
                .limit(match_count)
            )
            chunks = result.scalars().all()
            
            logger.debug(f"[PostgreSQL] Vector search returned {len(chunks)} chunks for document {doc_id}")
            return chunks
        
    # Check if database is connected.
    async def health_check(self) -> bool:
        try:
            async with self.async_session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
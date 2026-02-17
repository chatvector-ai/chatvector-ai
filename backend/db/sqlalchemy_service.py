import uuid
import logging
import os
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from core.models import DocumentChunk, Document
from db.base import ChunkMatch, DatabaseService

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
                file_name=filename,
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
        chunks_with_embeddings: list[tuple[str, list[float]]]
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

    async def create_document_with_chunks_atomic(
        self, 
        file_name: str, 
        chunks_with_embeddings: list[tuple[str, list[float]]]
    ) -> tuple[str, list[str]]:
        """Atomic document+chunk creation with transaction."""
        # Don't use self.async_session() directly - we need one session for everything
        async with self.async_session() as session:
            chunk_ids = []
            doc_id = str(uuid.uuid4())
            
            try:
                async with session.begin():
                    # Create document directly (don't call self.create_document)
                    document = Document(
                        id=doc_id,
                        file_name=file_name,
                        status="processing"
                    )
                    session.add(document)
                    
                    # Create chunks directly (don't call self.store_chunks_with_embeddings)
                    for chunk_text, embedding in chunks_with_embeddings:
                        chunk_id = str(uuid.uuid4())
                        chunk_ids.append(chunk_id)
                        chunk = DocumentChunk(
                            id=chunk_id,
                            document_id=doc_id,
                            chunk_text=chunk_text,
                            embedding=embedding,
                        )
                        session.add(chunk)
                
                logger.info(f"[PostgreSQL] Atomic upload: {doc_id} with {len(chunk_ids)} chunks")
                return doc_id, chunk_ids
                
            except Exception as e:
                logger.error(f"[PostgreSQL] Atomic upload failed: {e}")
                raise
    
    #Find chunks similar to query embedding using pgvector's cosine distance.Uses the <=> operator for cosine distance. 
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
            
            # Convert to ChunkMatch objects
            matches = [
                ChunkMatch(
                    id=chunk.id,
                    chunk_text=chunk.chunk_text,
                    document_id=chunk.document_id,
                    embedding=chunk.embedding,
                    created_at=str(chunk.created_at) if chunk.created_at else None,
                )
                for chunk in chunks
            ]
            
            logger.debug(f"[PostgreSQL] Vector search returned {len(matches)} chunks")
            return matches
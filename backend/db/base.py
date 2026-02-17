from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

# Abstract base class that defines WHAT database operations we need
# All DB services (sqlalchemy, supabase, mongodb etc.) must implement these methods.
# This ensures they're interchangeable.

@dataclass
class ChunkMatch:
    """Normalized chunk object returned by similarity search."""
    id: str
    chunk_text: str
    document_id: Optional[str] = None
    embedding: Optional[list[float]] = None
    created_at: Optional[str] = None
    similarity: Optional[float] = None

class DatabaseService(ABC):
    """Abstract base class for database services."""
    
    # Create a document record and return the document ID.
    @abstractmethod
    async def create_document(self, filename: str) -> str:
        pass
    
    # Insert multiple chunks and their embeddings, return list of IDs.
    @abstractmethod
    async def store_chunks_with_embeddings(
        self, 
        doc_id: str, 
        chunks_with_embeddings: list[tuple[str, list[float]]]
    ) -> list[str]:
        pass
    
    # Grab a document by ID.
    @abstractmethod
    async def get_document(self, doc_id: str) -> dict:
        pass

    # Find chunks similar to the query embedding using vector similarity.
    # Return list of ChunkMatch objects sorted by similarity.
    @abstractmethod
    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5
    ) -> list[ChunkMatch]:
        pass
    
    # Atomically create document and chunks in one operation.
    # Returns tuple of (document_id, list of chunk_ids).
    @abstractmethod
    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunks_with_embeddings: list[tuple[str, list[float]]]
    ) -> tuple[str, list[str]]:
        pass
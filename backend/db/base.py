from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

# Abstract base class that defines WHAT database operations we need.
# All DB services (sqlalchemy, supabase, etc.) must implement these methods.


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

    @abstractmethod
    async def create_document(self, filename: str) -> str:
        """Create a document record and return document ID."""
        pass

    @abstractmethod
    async def store_chunks_with_embeddings(
        self,
        doc_id: str,
        chunks_with_embeddings: list[tuple[str, list[float]]],
    ) -> list[str]:
        """Insert chunks/embeddings and return chunk IDs."""
        pass

    @abstractmethod
    async def get_document(self, doc_id: str) -> Optional[dict]:
        """Fetch a document by ID."""
        pass

    @abstractmethod
    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5,
    ) -> list[ChunkMatch]:
        """Run vector similarity search for chunks."""
        pass

    @abstractmethod
    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunks_with_embeddings: list[tuple[str, list[float]]],
    ) -> tuple[str, list[str]]:
        """Atomically create document with chunk records."""
        pass

    @abstractmethod
    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        failed_stage: Optional[str] = None,
        error_message: Optional[str] = None,
        chunks_total: Optional[int] = None,
        chunks_processed: Optional[int] = None,
    ) -> None:
        """Update upload status/progress metadata."""
        pass

    @abstractmethod
    async def get_document_status(self, doc_id: str) -> Optional[dict]:
        """Get document upload status payload for polling."""
        pass

    @abstractmethod
    async def delete_document_chunks(self, doc_id: str) -> None:
        """Delete all chunks for a document (cleanup on failures)."""
        pass

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

# Abstract base class that defines WHAT database operations we need.
# All DB services (sqlalchemy, supabase, etc.) must implement these methods.


@dataclass
class ChunkRecord:
    """Chunk payload passed to store_chunks_with_embeddings."""

    chunk_text: str
    embedding: list[float]
    chunk_index: int
    character_offset_start: int
    character_offset_end: int
    page_number: Optional[int] = None


@dataclass
class ChunkMatch:
    """Normalized chunk object returned by similarity search."""

    id: str
    chunk_text: str
    document_id: Optional[str] = None
    embedding: Optional[list[float]] = None
    created_at: Optional[str] = None
    similarity: Optional[float] = None
    chunk_index: Optional[int] = None
    page_number: Optional[int] = None
    character_offset_start: Optional[int] = None
    character_offset_end: Optional[int] = None
    file_name: Optional[str] = None


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
        chunk_records: list[ChunkRecord],
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
        chunk_records: list[ChunkRecord],
    ) -> tuple[str, list[str]]:
        """Atomically create document with chunk records."""
        pass

    @abstractmethod
    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        error: Optional[dict] = None,
        chunks: Optional[dict] = None,
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

    @abstractmethod
    async def fail_stale_documents(self, statuses: list[str]) -> int:
        """
        Bulk-update all documents whose status is in *statuses* to 'failed'.

        Used at startup to resolve documents that were left in an in-progress
        state by a previous server crash or restart.  Returns the number of
        documents updated.
        """
        pass

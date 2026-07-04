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
    async def create_document(self, filename: str, tenant_id: Optional[str] = None) -> str:
        """Create a document record and return document ID."""
        pass

    @abstractmethod
    async def store_chunks_with_embeddings(
        self,
        doc_id: str,
        chunk_records: list[ChunkRecord],
        tenant_id: Optional[str] = None,
    ) -> list[str]:
        """Insert chunks/embeddings and return chunk IDs."""
        pass

    @abstractmethod
    async def get_document(self, doc_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
        """Fetch a document by ID."""
        pass

    @abstractmethod
    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5,
        session_id: Optional[str] = None,
        query_text: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[ChunkMatch]:
        """Run vector similarity search for chunks (optionally hybrid with keyword search).

        When tenant_id is supplied, the query enforces document ownership at
        the database layer so that chunks from another tenant's document are
        never returned even if the caller presents a valid doc_id.
        """
        pass

    @abstractmethod
    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunk_records: list[ChunkRecord],
        tenant_id: Optional[str] = None,
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
        tenant_id: Optional[str] = None,
    ) -> None:
        """Update upload status/progress metadata."""
        pass

    @abstractmethod
    async def get_document_status(self, doc_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
        """Get document upload status payload for polling."""
        pass

    @abstractmethod
    async def delete_document_chunks(self, doc_id: str, tenant_id: Optional[str] = None) -> None:
        """Delete all chunks for a document (cleanup on failures)."""
        pass

    @abstractmethod
    async def delete_document(self, document_id: str, tenant_id: Optional[str] = None) -> None:
        """Delete a document and all its associated chunks atomically."""
        pass

    @abstractmethod
    async def fail_stale_documents(self, statuses: list[str], tenant_id: Optional[str] = None) -> set[str]:
        """
        Mark documents in any of the given statuses as failed.

        Returns the set of document IDs that were updated.
        """
        pass

    async def list_tenant_documents(self, tenant_id: str) -> list[str]:
        """Return IDs of all documents owned by tenant_id.

        Default implementation returns an empty list; backends that support
        tenant-scoped document listing should override this.
        """
        return []

    @abstractmethod
    async def store_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tenant_id: Optional[str] = None,
    ) -> str:
        """Store a single chat message (user or AI)."""
        pass

    @abstractmethod
    async def get_session_history(
        self,
        session_id: str,
        limit: int = 20,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        """Retrieve recent chat history for a session."""
        pass

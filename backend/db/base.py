from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

SCORE_TYPE_VECTOR = "vector"
SCORE_TYPE_HYBRID_RRF = "hybrid_rrf"
SCORE_TYPE_RERANKED = "reranked"

# Abstract base class that defines WHAT database operations we need.
# All DB service implementations must satisfy this interface.


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
    score_type: Optional[str] = None
    chunk_index: Optional[int] = None
    page_number: Optional[int] = None
    character_offset_start: Optional[int] = None
    character_offset_end: Optional[int] = None
    file_name: Optional[str] = None


class DatabaseService(ABC):
    """Abstract base class for database services."""

    # ── Tenant-scoped document operations ──────────────────────────────────────

    @abstractmethod
    async def create_document(self, filename: str, tenant_id: str) -> str:
        """Create a document record owned by tenant_id and return document ID."""
        pass

    @abstractmethod
    async def store_chunks_with_embeddings(
        self,
        doc_id: str,
        chunk_records: list[ChunkRecord],
        tenant_id: str,
    ) -> list[str]:
        """Insert chunks/embeddings for a tenant-owned document."""
        pass

    @abstractmethod
    async def get_document(self, doc_id: str, tenant_id: str) -> Optional[dict]:
        """Fetch a document by ID, scoped to tenant_id."""
        pass

    @abstractmethod
    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int,
        *,
        tenant_id: str,
        session_id: Optional[str] = None,
        query_text: Optional[str] = None,
    ) -> list[ChunkMatch]:
        """Run tenant-scoped vector/hybrid search for chunks."""
        pass

    @abstractmethod
    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunk_records: list[ChunkRecord],
        tenant_id: str,
    ) -> tuple[str, list[str]]:
        """Atomically create a tenant-owned document with chunk records."""
        pass

    @abstractmethod
    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        tenant_id: str,
        *,
        error: Optional[dict] = None,
        chunks: Optional[dict] = None,
    ) -> None:
        """Update upload status/progress metadata for a tenant-owned document."""
        pass

    @abstractmethod
    async def get_document_status(self, doc_id: str, tenant_id: str) -> Optional[dict]:
        """Get document upload status payload for a tenant-owned document."""
        pass

    @abstractmethod
    async def delete_document_chunks(self, doc_id: str, tenant_id: str) -> None:
        """Delete chunks for a tenant-owned document (cleanup on failures)."""
        pass

    @abstractmethod
    async def delete_document(self, document_id: str, tenant_id: str) -> None:
        """Delete a tenant-owned document and all its chunks."""
        pass

    # ── Administrative / cross-tenant operations ──────────────────────────────

    @abstractmethod
    async def list_applied_migrations(self) -> Optional[list[str]]:
        """Return ledger filenames, or ``None`` when the ledger is not installed."""
        pass

    @abstractmethod
    async def fail_stale_documents_global(self, statuses: list[str]) -> set[str]:
        """Mark in-progress documents as failed across all tenants on startup."""
        pass

    async def list_tenant_documents(self, tenant_id: str) -> list[str]:
        """Return IDs of all documents owned by tenant_id."""
        return []

    # ── Tenant-scoped chat history ────────────────────────────────────────────

    @abstractmethod
    async def store_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tenant_id: str,
    ) -> str:
        """Store a single chat message owned by tenant_id."""
        pass

    @abstractmethod
    async def get_session_history(
        self,
        session_id: str,
        tenant_id: str,
        *,
        limit: int = 20,
    ) -> list[dict]:
        """Retrieve recent chat history for a tenant-owned session."""
        pass

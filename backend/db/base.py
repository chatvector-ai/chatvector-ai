from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

SCORE_TYPE_VECTOR = "vector"
SCORE_TYPE_HYBRID_RRF = "hybrid_rrf"
SCORE_TYPE_RERANKED = "reranked"

# documents.status_detail values for staged replacement (migration 014). They are
# retrieval-neutral: only ``documents.status == "completed"`` gates retrieval.
REPLACEMENT_IN_PROGRESS = "replacement_in_progress"
REPLACEMENT_FAILED = "replacement_failed"

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
    """Normalized chunk object returned by similarity search.

    ``similarity`` holds the primary ranking score from the latest retrieval
    stage (cosine similarity, hybrid RRF, or reranked combined score), not
    necessarily cosine similarity alone.
    """

    id: str
    chunk_text: str
    document_id: Optional[str] = None
    embedding: Optional[list[float]] = None
    created_at: Optional[str] = None
    similarity: Optional[float] = None
    score_type: Optional[str] = None
    vector_score: Optional[float] = None
    full_text_score: Optional[float] = None
    rrf_score: Optional[float] = None
    reranker_score: Optional[float] = None
    rerank_order: Optional[int] = None
    chunk_index: Optional[int] = None
    page_number: Optional[int] = None
    character_offset_start: Optional[int] = None
    character_offset_end: Optional[int] = None
    file_name: Optional[str] = None


class DatabaseService(ABC):
    """Abstract base class for database services."""

    # ── Tenant-scoped document operations ──────────────────────────────────────

    @abstractmethod
    async def create_document(
        self, filename: str, tenant_id: str, metadata: Optional[dict] = None
    ) -> str:
        """Create a document record owned by tenant_id and return document ID.

        ``metadata`` is validated scalar JSON supplied at upload; ``None`` stores ``{}``.
        """
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
        hybrid_enabled: Optional[bool] = None,
    ) -> list[ChunkMatch]:
        """Run tenant-scoped vector/hybrid search for chunks.

        ``hybrid_enabled`` overrides the process hybrid flag for this call.
        ``None`` keeps ``HYBRID_RETRIEVAL_ENABLED``.
        """
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
        job_metadata_patch: Optional[dict] = None,
    ) -> None:
        """Update upload status/progress metadata for a tenant-owned document."""
        pass

    @abstractmethod
    async def merge_document_job_metadata(
        self,
        doc_id: str,
        tenant_id: str,
        patch: dict,
    ) -> None:
        """Merge keys into documents.job_metadata without changing status."""
        pass

    @abstractmethod
    async def set_document_artifact_uri(
        self,
        doc_id: str,
        tenant_id: str,
        artifact_uri: Optional[str],
    ) -> None:
        """Record or clear ``documents.artifact_uri`` for worker fetch."""
        pass

    @abstractmethod
    async def get_document_status(self, doc_id: str, tenant_id: str) -> Optional[dict]:
        """Get document upload status payload for a tenant-owned document."""
        pass

    @abstractmethod
    async def begin_document_replacement(self, doc_id: str, tenant_id: str) -> str:
        """Atomically claim a tenant-owned document for replacement.

        Returns ``"started"`` (``status_detail`` is now ``replacement_in_progress``;
        ``status`` and active chunks are untouched), ``"in_progress"`` when a
        replacement is already running, ``"not_eligible"`` when the document is
        not ``completed``/``failed``, or ``"not_found"``.
        """
        pass

    @abstractmethod
    async def set_document_status_detail(
        self,
        doc_id: str,
        status_detail: Optional[str],
        tenant_id: str,
        *,
        error: Optional[dict] = None,
        job_metadata_patch: Optional[dict] = None,
    ) -> None:
        """Set ``status_detail`` and ``error`` without changing ``status`` or chunks."""
        pass

    @abstractmethod
    async def replace_document_content(
        self,
        doc_id: str,
        chunk_records: list[ChunkRecord],
        tenant_id: str,
        *,
        file_name: str,
        metadata: Optional[dict] = None,
    ) -> list[str]:
        """Swap a document's active chunk set for ``chunk_records`` in one transaction.

        Also marks the document ``completed``, clears ``status_detail``/``error``,
        and updates ``file_name`` (and ``metadata`` when not ``None``). Readers see
        either the entire old chunk set or the entire new one, never a mix.
        """
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
        pass

    @abstractmethod
    async def filter_document_ids_by_metadata(
        self, tenant_id: str, doc_ids: list[str], metadata_filter: dict
    ) -> list[str]:
        """Return the subset of doc_ids owned by tenant_id whose metadata matches.

        ``metadata_filter`` is a validated v1 filter (exact match / ``in`` list,
        keys ANDed). Input order is preserved.
        """
        pass

    @abstractmethod
    async def list_tenant_document_summaries(self, tenant_id: str) -> list[dict]:
        """Return summary metadata for all documents owned by tenant_id."""
        pass

    @abstractmethod
    async def ping_and_count_tenant_documents(
        self, tenant_id: str
    ) -> tuple[bool, int | None]:
        """Verify DB connectivity and return tenant-scoped document count."""
        pass

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
    async def store_chat_turn(
        self,
        session_id: str,
        question: str,
        answer: str,
        tenant_id: str,
        *,
        sources: Optional[list] = None,
    ) -> tuple[str, str]:
        """Store a user/assistant chat turn atomically for a tenant-owned session.

        ``sources`` is copied onto the assistant row only. ``None`` (the default)
        leaves that column null; ``[]`` stores an empty generated-answer snapshot.
        """
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

    # ── Session persistence ───────────────────────────────────────────────────

    @abstractmethod
    async def create_session_record(self, session_id: str, tenant_id) -> "Session":
        """Create a new session record."""
        pass

    @abstractmethod
    async def get_or_create_session_record(
        self, session_id: str, tenant_id
    ) -> "Session | None":
        """Get or create a session record (conflict-safe)."""
        pass

    @abstractmethod
    async def get_session_record(self, session_id: str, tenant_id) -> "Session | None":
        """Fetch a session record scoped to tenant_id."""
        pass

    @abstractmethod
    async def list_session_records(self, tenant_id) -> list:
        """List session records for a tenant."""
        pass

    @abstractmethod
    async def delete_session_record(self, session_id: str, tenant_id) -> bool:
        """Delete a session record and its chat history."""
        pass

    @abstractmethod
    async def add_session_document(self, session_id: str, document_id: str) -> None:
        """Bind a document to a session (idempotent)."""
        pass

    @abstractmethod
    async def get_chat_message(self, message_id: str, tenant_id: str) -> Optional[dict]:
        """Fetch a chat message scoped to tenant_id."""
        pass

    @abstractmethod
    async def create_retrieval_feedback(
        self,
        *,
        tenant_id: str,
        session_id: str,
        feedback_type: str,
        rating: int,
        comment: Optional[str],
        message_id: Optional[str],
        document_id: Optional[str],
        chunk_index: Optional[int],
    ) -> dict:
        """Persist a feedback row and return the stored record."""
        pass

    @abstractmethod
    async def list_retrieval_feedback(
        self,
        *,
        tenant_id: str,
        session_id: Optional[str] = None,
        created_after=None,
        created_before=None,
        limit: int = 50,
    ) -> list[dict]:
        """List feedback rows for a tenant with optional filters."""
        pass

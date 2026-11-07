"""Dataclass response models used by the ChatVector Python SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

JSONDict = dict[str, Any]
JSONMapping = Mapping[str, Any]

RetrievalScope = Literal["session", "tenant"]
QueryTransformationStrategy = Literal["rewrite", "expand", "stepback", "none"]
RerankerProvider = Literal["similarity", "cohere"]

MATCH_COUNT_MIN = 1
MATCH_COUNT_MAX = 20


@dataclass(slots=True)
class RetrievalConfig:
    """Per-request retrieval overrides sent as a nested ``retrieval`` object."""

    match_count: int | None = None
    scope: RetrievalScope | None = None
    hybrid_enabled: bool | None = None
    reranking_enabled: bool | None = None
    reranker_provider: RerankerProvider | None = None
    query_transformation_enabled: bool | None = None
    query_transformation_strategy: QueryTransformationStrategy | None = None
    skip_history_transform: bool | None = None
    preset: str | None = None
    metadata_filter: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.match_count is not None:
            validate_match_count(self.match_count)

    def to_dict(self) -> JSONDict:
        """Serialize set fields to backend JSON keys; omit unset values."""
        payload: JSONDict = {}
        if self.match_count is not None:
            payload["match_count"] = self.match_count
        if self.scope is not None:
            payload["scope"] = self.scope
        if self.hybrid_enabled is not None:
            payload["hybrid_enabled"] = self.hybrid_enabled
        if self.reranking_enabled is not None:
            payload["reranking_enabled"] = self.reranking_enabled
        if self.reranker_provider is not None:
            payload["reranker_provider"] = self.reranker_provider
        if self.query_transformation_enabled is not None:
            payload["query_transformation_enabled"] = self.query_transformation_enabled
        if self.query_transformation_strategy is not None:
            payload["query_transformation_strategy"] = self.query_transformation_strategy
        if self.skip_history_transform is not None:
            payload["skip_history_transform"] = self.skip_history_transform
        if self.preset is not None:
            payload["preset"] = self.preset
        if self.metadata_filter is not None:
            payload["metadata_filter"] = dict(self.metadata_filter)
        return payload


@dataclass(slots=True)
class HistoryConfig:
    """Per-request history overrides sent as a nested ``history`` object."""

    retrieval_history_window: int | None = None
    generation_history_window: int | None = None
    history_aware_retrieval: bool | None = None
    max_generation_history_chars: int | None = None

    def to_dict(self) -> JSONDict:
        """Serialize set fields to backend JSON keys; omit unset values."""
        payload: JSONDict = {}
        if self.retrieval_history_window is not None:
            payload["retrieval_history_window"] = self.retrieval_history_window
        if self.generation_history_window is not None:
            payload["generation_history_window"] = self.generation_history_window
        if self.history_aware_retrieval is not None:
            payload["history_aware_retrieval"] = self.history_aware_retrieval
        if self.max_generation_history_chars is not None:
            payload["max_generation_history_chars"] = self.max_generation_history_chars
        return payload


def validate_match_count(value: int) -> None:
    """Reject match counts outside the backend-supported range before a request."""
    if value < MATCH_COUNT_MIN or value > MATCH_COUNT_MAX:
        raise ValueError(
            f"Invalid match_count={value}. Expected an integer from "
            f"{MATCH_COUNT_MIN} to {MATCH_COUNT_MAX}."
        )

_COMPONENT_SCORE_FIELDS = (
    "vector_score",
    "full_text_score",
    "rrf_score",
    "reranker_score",
    "rerank_order",
)

_RETRIEVAL_DEBUG_KNOWN_KEYS = frozenset(
    {
        "original_query",
        "transformed_queries",
        "transformation_strategy",
        "effective_retrieval_query",
        "timing_ms",
        "effective_config",
    }
)


@dataclass(slots=True)
class ChatSource:
    """Citation metadata describing a chunk used to answer a question."""

    file_name: str | None
    page_number: int | None
    chunk_index: int | None
    score: float | None = None
    score_type: str | None = None
    vector_score: float | None = None
    full_text_score: float | None = None
    rrf_score: float | None = None
    reranker_score: float | None = None
    rerank_order: int | None = None

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "ChatSource":
        """Build a source model from an API response payload."""
        rerank_order = payload.get("rerank_order")
        return cls(
            file_name=_optional_str(payload.get("file_name")),
            page_number=_optional_int(payload.get("page_number")),
            chunk_index=_optional_int(payload.get("chunk_index")),
            score=_optional_float(payload.get("score")),
            score_type=_optional_str(payload.get("score_type")),
            vector_score=_optional_float(payload.get("vector_score")),
            full_text_score=_optional_float(payload.get("full_text_score")),
            rrf_score=_optional_float(payload.get("rrf_score")),
            reranker_score=_optional_float(payload.get("reranker_score")),
            rerank_order=_optional_int(rerank_order) if rerank_order is not None else None,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        d: JSONDict = {
            "file_name": self.file_name,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
        }
        if self.score is not None:
            d["score"] = self.score
        if self.score_type is not None:
            d["score_type"] = self.score_type
        for field in _COMPONENT_SCORE_FIELDS:
            value = getattr(self, field)
            if value is not None:
                d[field] = value
        return d


@dataclass(slots=True)
class RetrievalDebugMetadata:
    """Opt-in retrieval debug payload from chat, stream, and batch responses."""

    original_query: str | None = None
    transformed_queries: list[str] | None = None
    transformation_strategy: str | None = None
    effective_retrieval_query: str | None = None
    timing_ms: JSONDict | None = None
    effective_config: JSONDict | None = None
    passthrough: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "RetrievalDebugMetadata":
        """Build a debug metadata model while retaining unknown backend fields."""
        raw = dict(payload)
        transformed = raw.get("transformed_queries")
        timing_ms = raw.get("timing_ms")
        effective_config = raw.get("effective_config")
        passthrough = {
            key: value
            for key, value in raw.items()
            if key not in _RETRIEVAL_DEBUG_KNOWN_KEYS
        }
        return cls(
            original_query=_optional_str(raw.get("original_query")),
            transformed_queries=_string_list(transformed)
            if isinstance(transformed, list)
            else None,
            transformation_strategy=_optional_str(raw.get("transformation_strategy")),
            effective_retrieval_query=_optional_str(raw.get("effective_retrieval_query")),
            timing_ms=dict(timing_ms) if isinstance(timing_ms, Mapping) else None,
            effective_config=dict(effective_config)
            if isinstance(effective_config, Mapping)
            else None,
            passthrough=passthrough,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        payload: JSONDict = dict(self.passthrough)
        if self.original_query is not None:
            payload["original_query"] = self.original_query
        if self.transformed_queries is not None:
            payload["transformed_queries"] = list(self.transformed_queries)
        if self.transformation_strategy is not None:
            payload["transformation_strategy"] = self.transformation_strategy
        if self.effective_retrieval_query is not None:
            payload["effective_retrieval_query"] = self.effective_retrieval_query
        if self.timing_ms is not None:
            payload["timing_ms"] = dict(self.timing_ms)
        if self.effective_config is not None:
            payload["effective_config"] = dict(self.effective_config)
        return payload


@dataclass(slots=True)
class DocumentResponse:
    """Initial response returned after uploading a document."""

    document_id: str
    status: str
    message: str | None = None
    queue_position: int | None = None
    status_endpoint: str | None = None
    status_detail: str | None = None
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "DocumentResponse":
        """Build an upload response model from an API response payload."""
        raw = dict(payload)
        return cls(
            document_id=str(payload.get("document_id", "")),
            status=str(payload.get("status", "")),
            message=_optional_str(payload.get("message")),
            queue_position=_optional_int(payload.get("queue_position")),
            status_endpoint=_optional_str(payload.get("status_endpoint")),
            status_detail=_optional_str(payload.get("status_detail")),
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        payload: JSONDict = {
            "document_id": self.document_id,
            "status": self.status,
        }
        if self.message is not None:
            payload["message"] = self.message
        if self.queue_position is not None:
            payload["queue_position"] = self.queue_position
        if self.status_endpoint is not None:
            payload["status_endpoint"] = self.status_endpoint
        if self.status_detail is not None:
            payload["status_detail"] = self.status_detail
        return payload


@dataclass(slots=True)
class DocumentStatus:
    """Current ingestion state for a document."""

    document_id: str
    status: str
    chunks: JSONDict | None = None
    created_at: str | None = None
    updated_at: str | None = None
    error: JSONDict | None = None
    queue_position: int | None = None
    status_detail: str | None = None
    job: JSONDict | None = None
    metadata: JSONDict | None = None
    file_name: str | None = None
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "DocumentStatus":
        """Build a document status model from an API response payload."""
        raw = dict(payload)
        chunks = payload.get("chunks")
        error = payload.get("error")
        job = payload.get("job")
        metadata = payload.get("metadata")
        return cls(
            document_id=str(payload.get("document_id", "")),
            status=str(payload.get("status", "")),
            chunks=dict(chunks) if isinstance(chunks, Mapping) else None,
            created_at=_optional_str(payload.get("created_at")),
            updated_at=_optional_str(payload.get("updated_at")),
            error=dict(error) if isinstance(error, Mapping) else None,
            queue_position=_optional_int(payload.get("queue_position")),
            status_detail=_optional_str(payload.get("status_detail")),
            job=dict(job) if isinstance(job, Mapping) else None,
            metadata=dict(metadata) if isinstance(metadata, Mapping) else None,
            file_name=_optional_str(payload.get("file_name")),
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        payload: JSONDict = {
            "document_id": self.document_id,
            "status": self.status,
        }
        if self.chunks is not None:
            payload["chunks"] = dict(self.chunks)
        if self.created_at is not None:
            payload["created_at"] = self.created_at
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at
        if self.error is not None:
            payload["error"] = dict(self.error)
        if self.queue_position is not None:
            payload["queue_position"] = self.queue_position
        if self.status_detail is not None:
            payload["status_detail"] = self.status_detail
        if self.job is not None:
            payload["job"] = dict(self.job)
        if self.metadata is not None:
            payload["metadata"] = dict(self.metadata)
        if self.file_name is not None:
            payload["file_name"] = self.file_name
        return payload


@dataclass(slots=True)
class ChatResponse:
    """Single-document chat response."""

    question: str
    doc_id: str
    chunks: int
    answer: str
    status: str = "ok"
    sources: list[ChatSource] = field(default_factory=list)
    error: JSONDict | None = None
    latency_ms: int = 0
    model: str = ""
    session_id: str | None = None
    retrieval_debug: RetrievalDebugMetadata | None = None
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "ChatResponse":
        """Build a chat response model from an API response payload."""
        raw = dict(payload)
        sources_payload = payload.get("sources")
        sources = _parse_sources(sources_payload)
        error = payload.get("error")
        status = str(payload.get("status") or "ok")
        debug_payload = payload.get("retrieval_debug")
        return cls(
            question=str(payload.get("question", "")),
            doc_id=str(payload.get("doc_id", "")),
            chunks=int(payload.get("chunks", 0)),
            answer=str(payload.get("answer", "")),
            status=status,
            sources=sources,
            error=dict(error) if isinstance(error, Mapping) else None,
            latency_ms=int(payload.get("latency_ms") or 0),
            model=str(payload.get("model") or ""),
            session_id=_optional_str(payload.get("session_id")),
            retrieval_debug=_parse_retrieval_debug(debug_payload),
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        payload: JSONDict = {
            "question": self.question,
            "doc_id": self.doc_id,
            "chunks": self.chunks,
            "answer": self.answer,
            "status": self.status,
            "sources": [source.to_dict() for source in self.sources],
            "latency_ms": self.latency_ms,
            "model": self.model,
        }
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.error is not None:
            payload["error"] = dict(self.error)
        if self.retrieval_debug is not None:
            payload["retrieval_debug"] = self.retrieval_debug.to_dict()
        return payload


@dataclass(slots=True)
class DocumentSummary:
    """One document row returned from ``GET /documents``."""

    document_id: str
    file_name: str | None
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    status_detail: str | None = None
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "DocumentSummary":
        """Build a document summary from an API response payload."""
        raw = dict(payload)
        return cls(
            document_id=str(payload.get("document_id", "")),
            file_name=_optional_str(payload.get("file_name")),
            status=str(payload.get("status", "")),
            created_at=_optional_str(payload.get("created_at")),
            updated_at=_optional_str(payload.get("updated_at")),
            status_detail=_optional_str(payload.get("status_detail")),
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        payload: JSONDict = {
            "document_id": self.document_id,
            "file_name": self.file_name,
            "status": self.status,
        }
        if self.created_at is not None:
            payload["created_at"] = self.created_at
        if self.updated_at is not None:
            payload["updated_at"] = self.updated_at
        if self.status_detail is not None:
            payload["status_detail"] = self.status_detail
        return payload


@dataclass(slots=True)
class DocumentListResponse:
    """Collection response returned from ``GET /documents``."""

    tenant_id: str
    documents: list[DocumentSummary] = field(default_factory=list)
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "DocumentListResponse":
        """Build a document list model from an API response payload."""
        raw = dict(payload)
        documents_payload = payload.get("documents")
        documents = [
            DocumentSummary.from_dict(item)
            for item in documents_payload
            if isinstance(item, Mapping)
        ] if isinstance(documents_payload, list) else []
        return cls(
            tenant_id=str(payload.get("tenant_id", "")),
            documents=documents,
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "documents": [document.to_dict() for document in self.documents],
        }


@dataclass(slots=True)
class SessionHistoryMessage:
    """One message returned from ``GET /sessions/{id}/history``."""

    id: str
    role: str
    content: str
    created_at: str | None = None
    sources: list[JSONDict] | None = None
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "SessionHistoryMessage":
        """Build a history message model from an API response payload."""
        raw = dict(payload)
        return cls(
            id=str(payload.get("id", "")),
            role=str(payload.get("role", "")),
            content=str(payload.get("content", "")),
            created_at=_optional_str(payload.get("created_at")),
            sources=_parse_history_sources(payload.get("sources")),
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        payload: JSONDict = {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "sources": self.sources,
        }
        if self.created_at is not None:
            payload["created_at"] = self.created_at
        return payload


@dataclass(slots=True)
class SessionHistoryResponse:
    """Collection response returned from ``GET /sessions/{id}/history``."""

    messages: list[SessionHistoryMessage] = field(default_factory=list)
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "SessionHistoryResponse":
        """Build a session history model from an API response payload."""
        raw = dict(payload)
        messages_payload = payload.get("messages")
        messages = [
            SessionHistoryMessage.from_dict(item)
            for item in messages_payload
            if isinstance(item, Mapping)
        ] if isinstance(messages_payload, list) else []
        return cls(messages=messages, raw=raw)

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        return {"messages": [message.to_dict() for message in self.messages]}


@dataclass(slots=True)
class Session:
    """Session metadata returned by the session management endpoints."""

    id: str
    tenant_id: str | None
    created_at: str
    last_active: str
    metadata: JSONDict
    document_ids: list[str]
    display_label: str = "New session"
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "Session":
        """Build a session model from an API response payload."""
        raw = dict(payload)
        metadata = payload.get("metadata")
        label = payload.get("display_label")
        return cls(
            id=str(payload.get("id", "")),
            tenant_id=_optional_str(payload.get("tenant_id")),
            created_at=str(payload.get("created_at", "")),
            last_active=str(payload.get("last_active", "")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
            document_ids=_string_list(payload.get("document_ids")),
            display_label=label if isinstance(label, str) and label else "New session",
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "metadata": dict(self.metadata),
            "document_ids": list(self.document_ids),
            "display_label": self.display_label,
        }


@dataclass(slots=True)
class SessionListResponse:
    """Collection response returned from ``GET /sessions``."""

    sessions: list[Session] = field(default_factory=list)
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "SessionListResponse":
        """Build a session list model from an API response payload."""
        raw = dict(payload)
        sessions_payload = payload.get("sessions")
        sessions = [
            Session.from_dict(item)
            for item in sessions_payload
            if isinstance(item, Mapping)
        ] if isinstance(sessions_payload, list) else []
        return cls(sessions=sessions, raw=raw)

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        return {"sessions": [session.to_dict() for session in self.sessions]}


FeedbackType = Literal["answer", "citation", "retrieval"]


@dataclass(slots=True)
class FeedbackItem:
    """One feedback record returned by ``POST /feedback`` or ``GET /feedback``."""

    id: str
    type: FeedbackType
    rating: int
    session_id: str
    created_at: str
    comment: str | None = None
    message_id: str | None = None
    document_id: str | None = None
    chunk_index: int | None = None
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "FeedbackItem":
        raw = dict(payload)
        feedback_type = payload.get("type")
        if feedback_type not in ("answer", "citation", "retrieval"):
            feedback_type = "answer"
        return cls(
            id=str(payload.get("id", "")),
            type=feedback_type,  # type: ignore[arg-type]
            rating=int(payload.get("rating", 0)),
            session_id=str(payload.get("session_id", "")),
            created_at=str(payload.get("created_at", "")),
            comment=_optional_str(payload.get("comment")),
            message_id=_optional_str(payload.get("message_id")),
            document_id=_optional_str(payload.get("document_id")),
            chunk_index=(
                int(payload["chunk_index"])
                if isinstance(payload.get("chunk_index"), int)
                else None
            ),
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        return {
            "id": self.id,
            "type": self.type,
            "rating": self.rating,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "comment": self.comment,
            "message_id": self.message_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
        }


@dataclass(slots=True)
class FeedbackListResponse:
    """Collection response returned from ``GET /feedback``."""

    feedback: list[FeedbackItem] = field(default_factory=list)
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "FeedbackListResponse":
        raw = dict(payload)
        items_payload = payload.get("feedback")
        feedback = [
            FeedbackItem.from_dict(item)
            for item in items_payload
            if isinstance(item, Mapping)
        ] if isinstance(items_payload, list) else []
        return cls(feedback=feedback, raw=raw)

    def to_dict(self) -> JSONDict:
        return {"feedback": [item.to_dict() for item in self.feedback]}


@dataclass(slots=True)
class StreamChatEvent:
    """One event emitted by ``ChatVectorClient.stream_chat()``."""

    type: Literal["token", "complete"]
    content: str | None = None
    session_id: str | None = None
    sources: list[ChatSource] = field(default_factory=list)
    latency_ms: int = 0
    model: str = ""
    retrieval_debug: RetrievalDebugMetadata | None = None
    message_id: str | None = None

    @classmethod
    def token(cls, content: str) -> "StreamChatEvent":
        """Build a token event."""
        return cls(type="token", content=content)

    @classmethod
    def complete(
        cls,
        *,
        session_id: str | None,
        sources: list[ChatSource],
        latency_ms: int,
        model: str,
        retrieval_debug: RetrievalDebugMetadata | None = None,
        message_id: str | None = None,
    ) -> "StreamChatEvent":
        """Build a structured completion event.

        ``message_id`` is optional. It is the persisted assistant message id
        when the server stored the turn, and ``None`` when the payload omits
        it. A missing id is not an error.
        """
        return cls(
            type="complete",
            session_id=session_id,
            sources=list(sources),
            latency_ms=latency_ms,
            model=model,
            retrieval_debug=retrieval_debug,
            message_id=message_id,
        )


@dataclass(slots=True)
class StreamErrorEvent:
    """Structured error payload from a streaming ``error`` SSE event."""

    code: str
    message: str
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "StreamErrorEvent":
        """Build an error event model from an SSE payload."""
        raw = dict(payload)
        return cls(
            code=str(payload.get("code", "")),
            message=str(payload.get("message", "")),
            raw=raw,
        )


@dataclass(slots=True)
class BatchChatQuery:
    """Input payload for one item in a batch chat request."""

    question: str
    doc_ids: list[str]
    match_count: int = 5
    session_id: str | None = None
    scope: RetrievalScope | None = None
    retrieval: RetrievalConfig | None = None
    history: HistoryConfig | None = None

    def __post_init__(self) -> None:
        validate_match_count(self.match_count)

    def to_dict(self) -> JSONDict:
        """Convert the batch query into the API request payload."""
        payload: JSONDict = {
            "question": self.question,
            "doc_ids": list(self.doc_ids),
            "match_count": self.match_count,
        }
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.scope is not None:
            payload["scope"] = self.scope
        _merge_nested_request_config(payload, retrieval=self.retrieval, history=self.history)
        return payload


@dataclass(slots=True)
class BatchChatResult:
    """One result item returned from ``POST /chat/batch``."""

    status: str
    question: str
    doc_ids: list[str]
    chunks: int
    answer: str | None = None
    sources: list[ChatSource] = field(default_factory=list)
    error: JSONDict | None = None
    latency_ms: int = 0
    model: str = ""
    session_id: str | None = None
    retrieval_debug: RetrievalDebugMetadata | None = None
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "BatchChatResult":
        """Build a batch result model from an API response payload."""
        raw = dict(payload)
        error = payload.get("error")
        return cls(
            status=str(payload.get("status", "")),
            question=str(payload.get("question", "")),
            doc_ids=_string_list(payload.get("doc_ids")),
            chunks=int(payload.get("chunks", 0)),
            answer=_optional_str(payload.get("answer")),
            sources=_parse_sources(payload.get("sources")),
            error=dict(error) if isinstance(error, Mapping) else None,
            latency_ms=int(payload.get("latency_ms") or 0),
            model=str(payload.get("model") or ""),
            session_id=_optional_str(payload.get("session_id")),
            retrieval_debug=_parse_retrieval_debug(payload.get("retrieval_debug")),
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        payload: JSONDict = {
            "status": self.status,
            "question": self.question,
            "doc_ids": list(self.doc_ids),
            "chunks": self.chunks,
            "latency_ms": self.latency_ms,
            "model": self.model,
        }
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if self.answer is not None:
            payload["answer"] = self.answer
        if self.sources:
            payload["sources"] = [source.to_dict() for source in self.sources]
        if self.error is not None:
            payload["error"] = dict(self.error)
        if self.retrieval_debug is not None:
            payload["retrieval_debug"] = self.retrieval_debug.to_dict()
        return payload


@dataclass(slots=True)
class BatchChatResponse:
    """Collection response returned from ``POST /chat/batch``."""

    count: int
    success_count: int
    failure_count: int
    results: list[BatchChatResult] = field(default_factory=list)
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "BatchChatResponse":
        """Build a batch chat response model from an API response payload."""
        raw = dict(payload)
        results_payload = payload.get("results")
        results = [
            BatchChatResult.from_dict(item)
            for item in results_payload
            if isinstance(item, Mapping)
        ] if isinstance(results_payload, list) else []
        return cls(
            count=int(payload.get("count", len(results))),
            success_count=int(payload.get("success_count", 0)),
            failure_count=int(payload.get("failure_count", 0)),
            results=results,
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        return {
            "count": self.count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(slots=True)
class BulkUploadResult:
    """Outcome for one file in a client-side bulk upload."""

    file_path: str
    success: bool
    document: DocumentResponse | None = None
    error: Any | None = None

    def to_dict(self) -> JSONDict:
        """Convert the result into a JSON-serializable dictionary."""
        payload: JSONDict = {
            "file_path": self.file_path,
            "success": self.success,
        }
        if self.document is not None:
            payload["document"] = self.document.to_dict()
        if self.error is not None:
            if isinstance(self.error, Mapping):
                payload["error"] = dict(self.error)
            elif hasattr(self.error, "message"):
                payload["error"] = {
                    "message": getattr(self.error, "message", str(self.error)),
                    "status_code": getattr(self.error, "status_code", None),
                }
            else:
                payload["error"] = str(self.error)
        return payload


@dataclass(slots=True)
class BulkUploadSummary:
    """Aggregate outcome for ``upload_many`` / ``upload_directory``."""

    count: int
    success_count: int
    failure_count: int
    results: list[BulkUploadResult] = field(default_factory=list)

    def to_dict(self) -> JSONDict:
        """Convert the summary into a JSON-serializable dictionary."""
        return {
            "count": self.count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "results": [result.to_dict() for result in self.results],
        }


def _optional_float(value: Any) -> float | None:
    """Safely coerce optional numeric values to floats."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _optional_int(value: Any) -> int | None:
    """Safely coerce optional numeric values to integers."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    """Safely coerce optional values to strings."""
    if value is None:
        return None
    return str(value)


def _string_list(value: Any) -> list[str]:
    """Convert an arbitrary JSON array into a list of strings."""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _parse_sources(value: Any) -> list[ChatSource]:
    """Parse source payloads into typed source models."""
    if not isinstance(value, list):
        return []
    return [ChatSource.from_dict(item) for item in value if isinstance(item, Mapping)]


def _parse_history_sources(value: Any) -> list[JSONDict] | None:
    """Parse a stored history snapshot, keeping ``None`` distinct from ``[]``.

    Extra location keys such as ``page_end`` are copied through rather than
    stripped so a later reader can render the citation from this JSON alone.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _parse_retrieval_debug(value: Any) -> RetrievalDebugMetadata | None:
    """Parse optional retrieval debug payloads into typed metadata."""
    if not isinstance(value, Mapping):
        return None
    return RetrievalDebugMetadata.from_dict(value)


def _merge_nested_request_config(
    payload: JSONDict,
    *,
    retrieval: RetrievalConfig | None,
    history: HistoryConfig | None,
) -> None:
    """Attach nested retrieval/history objects when at least one field is set."""
    if retrieval is not None:
        nested = retrieval.to_dict()
        if nested:
            payload["retrieval"] = nested
    if history is not None:
        nested = history.to_dict()
        if nested:
            payload["history"] = nested

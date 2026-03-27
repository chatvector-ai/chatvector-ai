"""Dataclass response models used by the ChatVector Python SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

JSONDict = dict[str, Any]
JSONMapping = Mapping[str, Any]


@dataclass(slots=True)
class ChatSource:
    """Citation metadata describing a chunk used to answer a question."""

    file_name: str | None
    page_number: int | None
    chunk_index: int | None

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "ChatSource":
        """Build a source model from an API response payload."""
        return cls(
            file_name=_optional_str(payload.get("file_name")),
            page_number=_optional_int(payload.get("page_number")),
            chunk_index=_optional_int(payload.get("chunk_index")),
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        return {
            "file_name": self.file_name,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
        }


@dataclass(slots=True)
class DocumentResponse:
    """Initial response returned after uploading a document."""

    document_id: str
    status: str
    message: str | None = None
    queue_position: int | None = None
    status_endpoint: str | None = None
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
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "DocumentStatus":
        """Build a document status model from an API response payload."""
        raw = dict(payload)
        chunks = payload.get("chunks")
        error = payload.get("error")
        return cls(
            document_id=str(payload.get("document_id", "")),
            status=str(payload.get("status", "")),
            chunks=dict(chunks) if isinstance(chunks, Mapping) else None,
            created_at=_optional_str(payload.get("created_at")),
            updated_at=_optional_str(payload.get("updated_at")),
            error=dict(error) if isinstance(error, Mapping) else None,
            queue_position=_optional_int(payload.get("queue_position")),
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
        return payload


@dataclass(slots=True)
class ChatResponse:
    """Single-document chat response."""

    question: str
    chunks: int
    answer: str
    sources: list[ChatSource] = field(default_factory=list)
    raw: JSONDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: JSONMapping) -> "ChatResponse":
        """Build a chat response model from an API response payload."""
        raw = dict(payload)
        sources_payload = payload.get("sources")
        sources = _parse_sources(sources_payload)
        return cls(
            question=str(payload.get("question", "")),
            chunks=int(payload.get("chunks", 0)),
            answer=str(payload.get("answer", "")),
            sources=sources,
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        return {
            "question": self.question,
            "chunks": self.chunks,
            "answer": self.answer,
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(slots=True)
class BatchChatQuery:
    """Input payload for one item in a batch chat request."""

    question: str
    doc_ids: list[str]
    match_count: int = 5

    def to_dict(self) -> JSONDict:
        """Convert the batch query into the API request payload."""
        return {
            "question": self.question,
            "doc_ids": list(self.doc_ids),
            "match_count": self.match_count,
        }


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
            raw=raw,
        )

    def to_dict(self) -> JSONDict:
        """Convert the model back to a JSON-serializable dictionary."""
        payload: JSONDict = {
            "status": self.status,
            "question": self.question,
            "doc_ids": list(self.doc_ids),
            "chunks": self.chunks,
        }
        if self.answer is not None:
            payload["answer"] = self.answer
        if self.sources:
            payload["sources"] = [source.to_dict() for source in self.sources]
        if self.error is not None:
            payload["error"] = dict(self.error)
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

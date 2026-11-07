"""Server-Sent Events parsing helpers for streaming chat."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx

from .exceptions import (
    ChatVectorAPIError,
    ChatVectorAuthError,
    ChatVectorRateLimitError,
    ChatVectorTimeoutError,
)
from .models import (
    ChatSource,
    DocumentStatus,
    StreamChatEvent,
    StreamErrorEvent,
    _parse_retrieval_debug,
)

_DONE_PAYLOAD = "[DONE]"


async def async_iter_stream_chat_events(
    lines: AsyncIterator[str],
    *,
    map_error: Any,
) -> AsyncIterator[StreamChatEvent]:
    """
    Parse SSE lines from an async streaming HTTP response into typed chat events.

    Args:
        lines: Async iterable of response lines from ``httpx.Response.aiter_lines``.
        map_error: Callable that converts ``StreamErrorEvent`` into SDK exceptions.

    Yields:
        Token and completion events. Legacy ``done`` events are ignored.

    Raises:
        ChatVectorAPIError: If the stream emits a structured error event.
    """
    event_name: str | None = None
    data_lines: list[str] = []

    async for line in lines:
        if line == "":
            if event_name is None and not data_lines:
                continue
            event = _dispatch_sse_event(event_name, "\n".join(data_lines), map_error)
            if event is not None:
                yield event
            event_name = None
            data_lines = []
            continue

        if line.startswith("event:"):
            event_name = line[len("event:") :].strip() or None
            continue

        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
            continue

    if event_name is not None or data_lines:
        event = _dispatch_sse_event(event_name, "\n".join(data_lines), map_error)
        if event is not None:
            yield event


def iter_stream_chat_events(
    lines: Iterator[str],
    *,
    map_error: Any,
) -> Iterator[StreamChatEvent]:
    """
    Parse SSE lines from a streaming HTTP response into typed chat events.

    Args:
        lines: Iterable of response lines from ``httpx.Response.iter_lines``.
        map_error: Callable that converts ``StreamErrorEvent`` into SDK exceptions.

    Yields:
        Token and completion events. Legacy ``done`` events are ignored.

    Raises:
        ChatVectorAPIError: If the stream emits a structured error event.
    """
    event_name: str | None = None
    data_lines: list[str] = []

    for line in lines:
        if line == "":
            if event_name is None and not data_lines:
                continue
            event = _dispatch_sse_event(event_name, "\n".join(data_lines), map_error)
            if event is not None:
                yield event
            event_name = None
            data_lines = []
            continue

        if line.startswith("event:"):
            event_name = line[len("event:") :].strip() or None
            continue

        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
            continue

    if event_name is not None or data_lines:
        event = _dispatch_sse_event(event_name, "\n".join(data_lines), map_error)
        if event is not None:
            yield event


def _dispatch_sse_event(
    event_name: str | None,
    data: str,
    map_error: Any,
) -> StreamChatEvent | None:
    """Convert one SSE event into a typed stream event, raise, or skip legacy done."""
    if event_name == "done" or data == _DONE_PAYLOAD:
        return None

    if event_name == "error":
        payload = _parse_json_object(data)
        error_event = StreamErrorEvent.from_dict(payload)
        raise map_error(error_event)

    if event_name == "token":
        content = json.loads(data)
        if not isinstance(content, str):
            raise ChatVectorAPIError(
                "ChatVector returned an unexpected token event payload.",
                details=content,
            )
        return StreamChatEvent.token(content)

    if event_name == "complete":
        payload = _parse_json_object(data)
        return StreamChatEvent.complete(
            session_id=_optional_str(payload.get("session_id")),
            sources=_parse_sources(payload.get("sources")),
            latency_ms=int(payload.get("latency_ms") or 0),
            model=str(payload.get("model") or ""),
            retrieval_debug=_parse_retrieval_debug(payload.get("retrieval_debug")),
            message_id=_optional_str(payload.get("message_id")),
        )

    raise ChatVectorAPIError(
        "ChatVector returned an unexpected streaming event.",
        details={"event": event_name, "data": data},
    )


async def async_iter_document_status_events(
    lines: AsyncIterator[str],
    *,
    map_error: Any,
) -> AsyncIterator[DocumentStatus]:
    """
    Parse SSE lines from an async document status stream into typed status payloads.

    Args:
        lines: Async iterable of response lines from ``httpx.Response.aiter_lines``.
        map_error: Callable that converts error payloads into SDK exceptions.

    Yields:
        Document status snapshots emitted by the ingestion stream.

    Raises:
        ChatVectorAPIError: If the stream emits a structured error event.
    """
    event_name: str | None = None
    data_lines: list[str] = []

    async for line in lines:
        if line == "":
            if event_name is None and not data_lines:
                continue
            event = _dispatch_document_status_sse_event(
                event_name, "\n".join(data_lines), map_error
            )
            if event is not None:
                yield event
            event_name = None
            data_lines = []
            continue

        if line.startswith("event:"):
            event_name = line[len("event:") :].strip() or None
            continue

        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
            continue

    if event_name is not None or data_lines:
        event = _dispatch_document_status_sse_event(
            event_name, "\n".join(data_lines), map_error
        )
        if event is not None:
            yield event


def iter_document_status_events(
    lines: Iterator[str],
    *,
    map_error: Any,
) -> Iterator[DocumentStatus]:
    """
    Parse SSE lines from a document status stream into typed status payloads.

    Args:
        lines: Iterable of response lines from ``httpx.Response.iter_lines``.
        map_error: Callable that converts error payloads into SDK exceptions.

    Yields:
        Document status snapshots emitted by the ingestion stream.

    Raises:
        ChatVectorAPIError: If the stream emits a structured error event.
    """
    event_name: str | None = None
    data_lines: list[str] = []

    for line in lines:
        if line == "":
            if event_name is None and not data_lines:
                continue
            event = _dispatch_document_status_sse_event(
                event_name, "\n".join(data_lines), map_error
            )
            if event is not None:
                yield event
            event_name = None
            data_lines = []
            continue

        if line.startswith("event:"):
            event_name = line[len("event:") :].strip() or None
            continue

        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
            continue

    if event_name is not None or data_lines:
        event = _dispatch_document_status_sse_event(
            event_name, "\n".join(data_lines), map_error
        )
        if event is not None:
            yield event


def _dispatch_document_status_sse_event(
    event_name: str | None,
    data: str,
    map_error: Any,
) -> DocumentStatus | None:
    """Convert one document-status SSE event into a model or raise."""
    if event_name == "error":
        payload = _parse_json_object(data)
        raise map_error(payload)

    if event_name == "status":
        payload = _parse_json_object(data)
        return DocumentStatus.from_dict(payload)

    raise ChatVectorAPIError(
        "ChatVector returned an unexpected document status streaming event.",
        details={"event": event_name, "data": data},
    )


def map_document_status_stream_error(payload: dict[str, Any]) -> ChatVectorAPIError:
    """Convert a document-status streaming error payload into an SDK exception."""
    message = str(payload.get("message") or "ChatVector document status stream failed.")
    if "timed out" in message.lower():
        return ChatVectorTimeoutError(message, details=payload)
    return ChatVectorAPIError(message, details=payload)


def map_stream_error(error: StreamErrorEvent) -> ChatVectorAPIError:
    """Convert a streaming error event into the matching SDK exception."""
    message = error.message or "ChatVector streaming request failed."
    details = error.raw or {"code": error.code, "message": error.message}

    if error.code in {"llm_missing_api_key", "llm_invalid_api_key"}:
        return ChatVectorAuthError(message, details=details)
    if error.code == "llm_rate_limited":
        return ChatVectorRateLimitError(message, details=details)
    if error.code == "llm_timeout_or_connection":
        return ChatVectorTimeoutError(message, details=details)
    return ChatVectorAPIError(message, details=details)


def raise_for_stream_response(response: httpx.Response, map_http_error: Any) -> None:
    """Raise SDK exceptions for non-success streaming HTTP responses."""
    if response.is_success:
        return
    raise map_http_error(response)


def _parse_json_object(data: str) -> dict[str, Any]:
    """Decode one SSE data payload as a JSON object."""
    try:
        payload = json.loads(data)
    except ValueError as exc:
        raise ChatVectorAPIError(
            "ChatVector returned a non-JSON streaming event payload.",
            details={"data": data},
        ) from exc

    if not isinstance(payload, dict):
        raise ChatVectorAPIError(
            "ChatVector returned an unexpected streaming event payload.",
            details=payload,
        )
    return payload


def _optional_str(value: Any) -> str | None:
    """Safely coerce optional values to strings."""
    if value is None:
        return None
    return str(value)


def _parse_sources(value: Any) -> list[ChatSource]:
    """Parse source payloads into typed source models."""
    if not isinstance(value, list):
        return []
    return [
        ChatSource.from_dict(item)
        for item in value
        if isinstance(item, dict)
    ]

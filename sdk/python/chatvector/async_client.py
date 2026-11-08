"""Asynchronous client for interacting with the ChatVector API."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from ._common import (
    JSONDict,
    JSONMapping,
    RETRYABLE_STATUS_CODES,
    build_batch_chat_payload,
    build_chat_payload,
    build_client_headers,
    build_upload_form_data,
    content_type_for_filename,
    cap_duration_to_deadline,
    default_error_message,
    encode_path_component,
    extract_error_details,
    is_retryable_method,
    map_http_error,
    msg_timeout_or_connection,
    msg_unexpected,
    normalize_base_url,
    parse_json_dict,
    remaining_monotonic_seconds,
    request_timeout_for_deadline,
    retry_after_seconds,
    serialize_batch_query,
)
from ._retry import RetryDeadlineExceeded, WantsRetry, retry_async
from ._sse import (
    async_iter_document_status_events,
    async_iter_stream_chat_events,
    map_document_status_stream_error,
    map_stream_error,
    raise_for_stream_response,
)
from .exceptions import (
    ChatVectorAPIError,
    ChatVectorTimeoutError,
)
from ._bulk_upload import (
    collect_directory_upload_paths,
    execute_bulk_uploads_async,
)
from .models import (
    BatchChatQuery,
    BatchChatResponse,
    BulkUploadResult,
    BulkUploadSummary,
    ChatResponse,
    DocumentListResponse,
    DocumentResponse,
    RetrievalPresetDiscoveryResponse,
    DocumentStatus,
    HistoryConfig,
    RetrievalConfig,
    RetrievalScope,
    Session,
    SessionHistoryResponse,
    SessionListResponse,
    FeedbackItem,
    FeedbackListResponse,
    FeedbackType,
    StreamChatEvent,
)


class AsyncChatVectorClient:
    """Async convenience wrapper around the ChatVector HTTP API."""

    _RETRYABLE_STATUS_CODES = RETRYABLE_STATUS_CODES

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        """
        Create an asynchronous ChatVector API client.

        Args:
            base_url: Root URL for the ChatVector API, such as
                ``https://api.chatvector.example``.
            api_key: Optional bearer token used for authenticated requests.
        """
        normalized_base_url = normalize_base_url(base_url)
        headers = build_client_headers(api_key)

        self.base_url = normalized_base_url
        self.api_key = api_key
        self.max_retries = 2
        self.retry_backoff = 0.5
        self._default_timeout = 30.0
        self._client = httpx.AsyncClient(
            base_url=normalized_base_url,
            headers=headers,
            timeout=self._default_timeout,
            follow_redirects=True,
        )

    async def __aenter__(self) -> "AsyncChatVectorClient":
        """Support use as an async context manager."""
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        """Close the underlying HTTP client when exiting a context manager."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def upload_document(
        self,
        file_path: str,
        *,
        session_id: str | None = None,
        replace_document_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> DocumentResponse:
        """
        Upload a document for ingestion.

        The SDK targets ``POST /ingest`` and transparently falls back to the
        repository's current ``POST /upload`` route when needed.

        Pass ``replace_document_id`` to re-ingest an existing completed or failed
        document in place: it keeps its ID, and its prior content stays
        retrievable until the new content is ready (use ``wait_for_ready`` to
        wait for the swap).

        ``metadata`` is an optional document metadata object sent as the
        multipart JSON ``metadata`` field. It is omitted entirely when unset.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Document file was not found: {file_path}")

        content_type = content_type_for_filename(path.name)
        endpoints = ("ingest", "upload")
        last_error: ChatVectorAPIError | None = None
        headers: JSONDict = {}
        if session_id is not None:
            headers["X-Session-Id"] = session_id
        if idempotency_key is not None:
            if not idempotency_key.strip():
                raise ValueError("idempotency_key must not be empty.")
            headers["Idempotency-Key"] = idempotency_key.strip()
        request_headers: JSONDict | None = headers or None
        form_data = build_upload_form_data(
            replace_document_id=replace_document_id,
            metadata=metadata,
        )

        for endpoint in endpoints:
            with path.open("rb") as file_handle:
                files = {"file": (path.name, file_handle, content_type)}
                try:
                    payload = await self._request_json(
                        "POST",
                        endpoint,
                        files=files,
                        headers=request_headers,
                        **({} if form_data is None else {"data": form_data}),
                    )
                    return DocumentResponse.from_dict(payload)
                except ChatVectorAPIError as exc:
                    if endpoint == "ingest" and exc.status_code == 404:
                        last_error = exc
                        continue
                    raise

        if last_error is None:
            raise ChatVectorAPIError("Document upload failed for an unknown reason.")
        raise last_error

    async def upload_many(
        self,
        file_paths: Sequence[str],
        *,
        concurrency: int = 5,
        session_id: str | None = None,
        fail_fast: bool = False,
        retry_on_rate_limit: bool = False,
        max_rate_limit_retries: int = 1,
        idempotency_key_for: Callable[[str], str | None] | None = None,
        on_progress: Callable[[BulkUploadResult, BulkUploadSummary], None] | None = None,
        wait_for_ready: bool = False,
        wait_timeout: float = 60.0,
        wait_interval: float = 2.0,
    ) -> BulkUploadSummary:
        """Async variant of ``ChatVectorClient.upload_many``."""

        async def upload_fn(
            file_path: str,
            idempotency_key: str | None,
        ) -> DocumentResponse:
            return await self.upload_document(
                file_path,
                session_id=session_id,
                idempotency_key=idempotency_key,
            )

        wait_ready_fn = None
        if wait_for_ready:

            async def wait_ready_fn(document_id: str) -> None:
                await self.wait_for_ready(
                    document_id,
                    timeout=wait_timeout,
                    interval=wait_interval,
                )

        return await execute_bulk_uploads_async(
            file_paths,
            upload_fn,
            concurrency=concurrency,
            fail_fast=fail_fast,
            retry_on_rate_limit=retry_on_rate_limit,
            max_rate_limit_retries=max_rate_limit_retries,
            idempotency_key_for=idempotency_key_for,
            on_progress=on_progress,
            wait_ready_fn=wait_ready_fn,
        )

    async def upload_directory(
        self,
        directory_path: str,
        *,
        pattern: str = "*",
        recursive: bool = True,
        concurrency: int = 5,
        session_id: str | None = None,
        fail_fast: bool = False,
        retry_on_rate_limit: bool = False,
        max_rate_limit_retries: int = 1,
        idempotency_key_for: Callable[[str], str | None] | None = None,
        on_progress: Callable[[BulkUploadResult, BulkUploadSummary], None] | None = None,
        wait_for_ready: bool = False,
        wait_timeout: float = 60.0,
        wait_interval: float = 2.0,
    ) -> BulkUploadSummary:
        """Async variant of ``ChatVectorClient.upload_directory``."""
        paths = collect_directory_upload_paths(
            directory_path,
            pattern=pattern,
            recursive=recursive,
        )
        return await self.upload_many(
            [str(path) for path in paths],
            concurrency=concurrency,
            session_id=session_id,
            fail_fast=fail_fast,
            retry_on_rate_limit=retry_on_rate_limit,
            max_rate_limit_retries=max_rate_limit_retries,
            idempotency_key_for=idempotency_key_for,
            on_progress=on_progress,
            wait_for_ready=wait_for_ready,
            wait_timeout=wait_timeout,
            wait_interval=wait_interval,
        )

    async def get_status(
        self,
        document_id: str,
        *,
        deadline_monotonic: float | None = None,
    ) -> DocumentStatus:
        """Fetch the ingestion status for a document."""
        encoded_id = encode_path_component(document_id)
        payload = await self._request_json(
            "GET",
            f"documents/{encoded_id}/status",
            deadline_monotonic=deadline_monotonic,
        )
        return DocumentStatus.from_dict(payload)

    async def list_documents(self) -> DocumentListResponse:
        """List document summaries for the authenticated tenant."""
        payload = await self._request_json("GET", "documents")
        return DocumentListResponse.from_dict(payload)

    async def list_retrieval_presets(self) -> RetrievalPresetDiscoveryResponse:
        """List loaded preset names and reranker identifiers for this process."""
        payload = await self._request_json("GET", "retrieval/presets")
        return RetrievalPresetDiscoveryResponse.from_dict(payload)

    async def delete_document(self, document_id: str) -> None:
        """Delete a document by identifier."""
        encoded_id = encode_path_component(document_id)
        await self._request_no_content("DELETE", f"documents/{encoded_id}")

    async def create_session(
        self,
        session_id: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Session:
        """Create a new chat session."""
        body: JSONDict = {}
        if session_id is not None:
            body["session_id"] = session_id
        headers: JSONDict | None = None
        if idempotency_key is not None:
            if not idempotency_key.strip():
                raise ValueError("idempotency_key must not be empty.")
            headers = {"Idempotency-Key": idempotency_key.strip()}
        payload = await self._request_json(
            "POST", "sessions", json=body, headers=headers
        )
        return Session.from_dict(payload)

    async def get_session(self, session_id: str) -> Session:
        """Fetch session metadata by identifier."""
        payload = await self._request_json(
            "GET",
            f"sessions/{encode_path_component(session_id)}",
        )
        return Session.from_dict(payload)

    async def get_session_history(self, session_id: str) -> SessionHistoryResponse:
        """Fetch chat message history for a session."""
        encoded_id = encode_path_component(session_id)
        payload = await self._request_json("GET", f"sessions/{encoded_id}/history")
        return SessionHistoryResponse.from_dict(payload)

    async def list_sessions(self) -> SessionListResponse:
        """List all sessions for the authenticated tenant."""
        payload = await self._request_json("GET", "sessions")
        return SessionListResponse.from_dict(payload)

    async def post_feedback(
        self,
        *,
        feedback_type: FeedbackType,
        rating: int,
        session_id: str,
        comment: str | None = None,
        message_id: str | None = None,
        document_id: str | None = None,
        chunk_index: int | None = None,
    ) -> FeedbackItem:
        """Submit structured feedback for an answer, citation, or retrieval result."""
        if rating not in (-1, 1):
            raise ValueError("rating must be -1 or 1.")
        body: JSONDict = {
            "type": feedback_type,
            "rating": rating,
            "session_id": session_id,
        }
        if comment is not None:
            body["comment"] = comment
        if message_id is not None:
            body["message_id"] = message_id
        if document_id is not None:
            body["document_id"] = document_id
        if chunk_index is not None:
            body["chunk_index"] = chunk_index
        payload = await self._request_json("POST", "feedback", json=body)
        return FeedbackItem.from_dict(payload)

    async def list_feedback(
        self,
        *,
        session_id: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int | None = None,
    ) -> FeedbackListResponse:
        """List feedback records for the authenticated tenant."""
        params: dict[str, str | int] = {}
        if session_id is not None:
            params["session_id"] = session_id
        if created_after is not None:
            params["created_after"] = created_after
        if created_before is not None:
            params["created_before"] = created_before
        if limit is not None:
            params["limit"] = limit
        payload = await self._request_json("GET", "feedback", params=params or None)
        return FeedbackListResponse.from_dict(payload)

    async def delete_session(self, session_id: str) -> None:
        """Delete a session by identifier."""
        await self._request_no_content(
            "DELETE",
            f"sessions/{encode_path_component(session_id)}",
        )

    async def chat(
        self,
        question: str,
        doc_id: str,
        match_count: int = 5,
        session_id: str | None = None,
        scope: RetrievalScope | None = None,
        debug_retrieval: bool = False,
        retrieval: RetrievalConfig | None = None,
        history: HistoryConfig | None = None,
    ) -> ChatResponse:
        """Ask a question against a single document."""
        payload = build_chat_payload(
            question=question,
            doc_id=doc_id,
            match_count=match_count,
            session_id=session_id,
            scope=scope,
            debug_retrieval=debug_retrieval,
            retrieval=retrieval,
            history=history,
        )
        response_payload = await self._request_json("POST", "chat", json=payload)
        return ChatResponse.from_dict(response_payload)

    def stream_chat(
        self,
        question: str,
        doc_id: str,
        match_count: int = 5,
        session_id: str | None = None,
        scope: RetrievalScope | None = None,
        debug_retrieval: bool = False,
        retrieval: RetrievalConfig | None = None,
        history: HistoryConfig | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> AsyncIterator[StreamChatEvent]:
        """Stream a chat answer as typed Server-Sent Events."""
        payload = build_chat_payload(
            question=question,
            doc_id=doc_id,
            match_count=match_count,
            session_id=session_id,
            scope=scope,
            debug_retrieval=debug_retrieval,
            retrieval=retrieval,
            history=history,
        )

        request_kwargs: JSONDict = {"json": payload}
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        return self._aiter_stream_chat_events(request_kwargs)

    async def _aiter_stream_chat_events(
        self,
        request_kwargs: JSONDict,
    ) -> AsyncIterator[StreamChatEvent]:
        """Open a streaming chat request and yield parsed SSE events."""
        try:
            async with self._client.stream("POST", "chat/stream", **request_kwargs) as response:
                raise_for_stream_response(response, self._map_http_error)
                try:
                    async for event in async_iter_stream_chat_events(
                        response.aiter_lines(),
                        map_error=map_stream_error,
                    ):
                        yield event
                finally:
                    await response.aclose()
        except httpx.TimeoutException as exc:
            raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
        except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
        except httpx.HTTPStatusError as exc:
            raise self._map_http_error(exc.response) from exc
        except httpx.RequestError as exc:
            raise ChatVectorAPIError(
                msg_unexpected(), details={"error": str(exc)}
            ) from exc

    async def batch_chat(
        self,
        queries: Sequence[BatchChatQuery | JSONMapping],
        session_id: str | None = None,
        scope: RetrievalScope | None = None,
        debug_retrieval: bool = False,
        retrieval: RetrievalConfig | None = None,
        history: HistoryConfig | None = None,
    ) -> BatchChatResponse:
        """Run multiple chat queries in a single API call.

        A batch item that names exactly one document is compare-style: session
        history is not injected and successful turns are not persisted, even when
        ``session_id`` is set.
        """
        payload = build_batch_chat_payload(
            queries=queries,
            session_id=session_id,
            scope=scope,
            debug_retrieval=debug_retrieval,
            retrieval=retrieval,
            history=history,
        )
        response_payload = await self._request_json("POST", "chat/batch", json=payload)
        return BatchChatResponse.from_dict(response_payload)

    def iter_document_status(
        self,
        document_id: str,
        timeout: float | httpx.Timeout | None = None,
    ) -> AsyncIterator[DocumentStatus]:
        """Stream document ingestion status updates as typed Server-Sent Events."""
        request_kwargs: JSONDict = {}
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        encoded_id = encode_path_component(document_id)
        return self._aiter_document_status_events(encoded_id, request_kwargs)

    async def _aiter_document_status_events(
        self,
        document_id: str,
        request_kwargs: JSONDict,
    ) -> AsyncIterator[DocumentStatus]:
        """Open a document status stream and yield parsed SSE events."""
        try:
            async with self._client.stream(
                "GET",
                f"documents/{document_id}/status/stream",
                **request_kwargs,
            ) as response:
                raise_for_stream_response(response, self._map_http_error)
                try:
                    async for event in async_iter_document_status_events(
                        response.aiter_lines(),
                        map_error=map_document_status_stream_error,
                    ):
                        yield event
                finally:
                    await response.aclose()
        except httpx.TimeoutException as exc:
            raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
        except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
        except httpx.HTTPStatusError as exc:
            raise self._map_http_error(exc.response) from exc
        except httpx.RequestError as exc:
            raise ChatVectorAPIError(
                msg_unexpected(), details={"error": str(exc)}
            ) from exc

    async def wait_for_ready(
        self,
        document_id: str,
        timeout: int = 60,
        interval: int = 2,
    ) -> DocumentStatus:
        """Poll the document status endpoint until ingestion completes or fails."""
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0.")
        if interval <= 0:
            raise ValueError("interval must be greater than 0.")

        deadline = time.monotonic() + timeout
        last_response: DocumentStatus | None = None

        while True:
            if remaining_monotonic_seconds(deadline) == 0.0:
                raise self._wait_timeout_error(document_id, timeout, last_response)
            try:
                last_response = await self.get_status(
                    document_id,
                    deadline_monotonic=deadline,
                )
            except RetryDeadlineExceeded:
                raise self._wait_timeout_error(document_id, timeout, last_response) from None
            status = last_response.status
            status_detail = last_response.status_detail

            # A replacement keeps `status` completed/failed while it runs, so only
            # `status_detail` says whether the latest content is ready yet.
            if status_detail == "replacement_in_progress":
                pass
            elif status == "completed" and status_detail != "replacement_failed":
                return last_response
            elif status == "failed" or status_detail == "replacement_failed":
                stage_label = (
                    "replacement" if status_detail == "replacement_failed" else "processing"
                )
                message = f"Document '{document_id}' {stage_label} failed."
                error_payload = last_response.error
                if isinstance(error_payload, dict):
                    error_message = error_payload.get("message")
                    if isinstance(error_message, str) and error_message:
                        message = f"{message} {error_message}"
                raise ChatVectorAPIError(message, details=last_response.to_dict())

            remaining = remaining_monotonic_seconds(deadline)
            if remaining is None or remaining <= 0:
                raise self._wait_timeout_error(document_id, timeout, last_response)

            await asyncio.sleep(cap_duration_to_deadline(float(interval), deadline))

    def _wait_timeout_error(
        self,
        document_id: str,
        timeout: int,
        last_response: DocumentStatus | None,
    ) -> ChatVectorTimeoutError:
        """Build the standard wait-for-ready timeout exception."""
        details = last_response.to_dict() if last_response is not None else None
        return ChatVectorTimeoutError(
            f"Timed out after {timeout} second(s) while waiting for document "
            f"'{document_id}' to be ready.",
            status_code=408,
            details=details,
        )

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        deadline_monotonic: float | None = None,
        **kwargs: Any,
    ) -> JSONDict:
        """Send an HTTP request and return the decoded JSON object response."""
        response = await self._request_response(
            method,
            url,
            deadline_monotonic=deadline_monotonic,
            **kwargs,
        )
        return self._parse_json_dict(response)

    async def _request_no_content(
        self,
        method: str,
        url: str,
        *,
        deadline_monotonic: float | None = None,
        **kwargs: Any,
    ) -> None:
        """Send an HTTP request that returns no response body on success."""
        await self._request_response(
            method,
            url,
            deadline_monotonic=deadline_monotonic,
            **kwargs,
        )

    async def _request_response(
        self,
        method: str,
        url: str,
        *,
        deadline_monotonic: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request with retry support and return the raw response."""
        max_attempts = self.max_retries + 1
        call_idx = [0]
        retryable_method = is_retryable_method(method)
        request_kwargs = dict(kwargs)
        if "timeout" not in request_kwargs:
            request_kwargs["timeout"] = request_timeout_for_deadline(
                self._default_timeout,
                deadline_monotonic,
            )

        async def _attempt() -> httpx.Response:
            i = call_idx[0]
            call_idx[0] += 1
            if (
                deadline_monotonic is not None
                and remaining_monotonic_seconds(deadline_monotonic) == 0.0
            ):
                raise RetryDeadlineExceeded()
            per_attempt_kwargs = dict(request_kwargs)
            per_attempt_kwargs["timeout"] = request_timeout_for_deadline(
                float(per_attempt_kwargs.get("timeout", self._default_timeout)),
                deadline_monotonic,
            )
            try:
                response = await self._client.request(method, url, **per_attempt_kwargs)
                if response.status_code in self._RETRYABLE_STATUS_CODES:
                    if retryable_method and i + 1 < max_attempts:
                        raise WantsRetry(self._retry_after_seconds(response))
                    response.raise_for_status()
                    return response
                response.raise_for_status()
                return response
            except httpx.TimeoutException as exc:
                if retryable_method and i + 1 < max_attempts:
                    raise WantsRetry(0.0) from exc
                raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
            except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if retryable_method and i + 1 < max_attempts:
                    raise WantsRetry(0.0) from exc
                raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
            except httpx.HTTPStatusError as exc:
                if (
                    retryable_method
                    and exc.response.status_code in self._RETRYABLE_STATUS_CODES
                    and i + 1 < max_attempts
                ):
                    raise WantsRetry(self._retry_after_seconds(exc.response)) from exc
                raise self._map_http_error(exc.response) from exc
            except httpx.RequestError as exc:
                raise ChatVectorAPIError(
                    msg_unexpected(), details={"error": str(exc)}
                ) from exc

        return await retry_async(
            _attempt,
            max_retries=self.max_retries,
            base_delay=self.retry_backoff,
            backoff=2.0,
            func_name="_request_response",
            deadline_monotonic=deadline_monotonic,
        )

    def _map_http_error(self, response: httpx.Response) -> ChatVectorAPIError:
        """Convert an HTTP error response into the matching ChatVector exception."""
        return map_http_error(response)

    def _extract_error_details(self, response: httpx.Response) -> tuple[str, Any | None]:
        """Extract a readable error message and payload from an HTTP response."""
        return extract_error_details(response)

    def _parse_json_dict(self, response: httpx.Response) -> JSONDict:
        """Decode a response body as a JSON object."""
        return parse_json_dict(response)

    def _default_error_message(self, status_code: int) -> str:
        """Return a classification-based fallback error message."""
        return default_error_message(status_code)

    def _retry_after_seconds(self, response: httpx.Response) -> float:
        """Parse Retry-After as seconds, or 0.0 if absent or invalid."""
        return retry_after_seconds(response)

    def _serialize_batch_query(self, query: BatchChatQuery | JSONMapping) -> JSONDict:
        """Normalize a batch query into the JSON payload expected by the API."""
        return serialize_batch_query(query)

    def _msg_timeout_or_connection(self) -> str:
        """Return the standard timeout or connection failure message."""
        return msg_timeout_or_connection()

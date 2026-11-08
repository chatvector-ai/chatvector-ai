"""Synchronous client for interacting with the ChatVector API."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from ._retry import RetryDeadlineExceeded, WantsRetry, retry_sync
from ._sse import (
    iter_document_status_events,
    iter_stream_chat_events,
    map_document_status_stream_error,
    map_stream_error,
    raise_for_stream_response,
)
from .exceptions import (
    ChatVectorAPIError,
    ChatVectorAuthError,
    ChatVectorRateLimitError,
    ChatVectorTimeoutError,
)
from ._bulk_upload import collect_directory_upload_paths, execute_bulk_uploads
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
from ._common import (
    JSONDict,
    JSONMapping,
    RETRYABLE_STATUS_CODES,
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
    build_batch_chat_payload,
    build_chat_payload,
    build_upload_form_data,
    content_type_for_filename,
    serialize_batch_query,
    build_client_headers,
)


class ChatVectorClient:
    """Convenience wrapper around the ChatVector HTTP API."""

    _RETRYABLE_STATUS_CODES = RETRYABLE_STATUS_CODES

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        """
        Create a synchronous ChatVector API client.

        Args:
            base_url: Root URL for the ChatVector API, such as
                ``https://api.chatvector.example``.
            api_key: Optional bearer token used for authenticated requests.
        """
        if not base_url.strip():
            raise ValueError("base_url must not be empty.")

        normalized_base_url = normalize_base_url(base_url)
        headers = build_client_headers(api_key)

        self.base_url = normalized_base_url
        self.api_key = api_key
        self.max_retries = 2
        self.retry_backoff = 0.5
        self._default_timeout = 30.0
        self._client = httpx.Client(
            base_url=normalized_base_url,
            headers=headers,
            timeout=self._default_timeout,
            follow_redirects=True,
        )

    def __enter__(self) -> "ChatVectorClient":
        """Support use as a context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        """Close the underlying HTTP client when exiting a context manager."""
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def upload_document(
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

        Args:
            file_path: Path to the document on disk.
            session_id: Optional session to bind the document to.
            replace_document_id: Optional ID of an existing completed or failed
                document to re-ingest in place. The document keeps its ID and its
                prior content stays retrievable until the new content is ready;
                use ``wait_for_ready`` to wait for the swap. Raises
                ``ChatVectorAPIError`` (409) if a replacement is already running.
            idempotency_key: Optional ``Idempotency-Key`` header for safe retries.
            metadata: Optional document metadata sent as the multipart JSON
                ``metadata`` field. Omitted entirely when unset.

        Returns:
            A typed upload response with the document identifier and status.
            For a replacement, ``status`` is the document's current status and
            ``status_detail`` is ``"replacement_in_progress"``.

        Raises:
            FileNotFoundError: If the file does not exist.
            ChatVectorAPIError: If the API returns an error response.
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
                    payload = self._request_json(
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

    def upload_many(
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
        """
        Upload many documents using repeated ``POST /upload`` (or ``/ingest``).

        Each file is uploaded independently with bounded concurrency. Failures
        are captured per file; remaining uploads continue unless ``fail_fast``
        is enabled. Mutating uploads are not retried unless
        ``retry_on_rate_limit`` is set (bounded by ``max_rate_limit_retries``).

        Large batches often receive HTTP 429 under the default server upload
        rate limit (typically 20 uploads per hour per tenant).
        """

        def upload_fn(
            file_path: str,
            idempotency_key: str | None,
        ) -> DocumentResponse:
            return self.upload_document(
                file_path,
                session_id=session_id,
                idempotency_key=idempotency_key,
            )

        wait_ready_fn = None
        if wait_for_ready:

            def wait_ready_fn(document_id: str) -> None:
                self.wait_for_ready(
                    document_id,
                    timeout=wait_timeout,
                    interval=wait_interval,
                )

        return execute_bulk_uploads(
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

    def upload_directory(
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
        """
        Upload regular files under a directory with traversal guards.

        Rejects ``..`` segments and symlink targets that escape the directory
        root. Remaining options match ``upload_many``.
        """
        paths = collect_directory_upload_paths(
            directory_path,
            pattern=pattern,
            recursive=recursive,
        )
        return self.upload_many(
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

    def get_status(
        self,
        document_id: str,
        *,
        deadline_monotonic: float | None = None,
    ) -> DocumentStatus:
        """
        Fetch the ingestion status for a document.

        Args:
            document_id: The document identifier returned by ``upload_document``.
            deadline_monotonic: Optional absolute poll deadline for internal use.

        Returns:
            A typed document status response.
        """
        encoded_id = encode_path_component(document_id)
        payload = self._request_json(
            "GET",
            f"documents/{encoded_id}/status",
            deadline_monotonic=deadline_monotonic,
        )
        return DocumentStatus.from_dict(payload)

    def list_documents(self) -> DocumentListResponse:
        """
        List document summaries for the authenticated tenant.

        Returns:
            A typed list of tenant document summaries.
        """
        payload = self._request_json("GET", "documents")
        return DocumentListResponse.from_dict(payload)

    def list_retrieval_presets(self) -> RetrievalPresetDiscoveryResponse:
        """
        List loaded retrieval preset names and configured reranker identifiers.

        Returns:
            Preset names (no bodies) and reranker provider identifiers for this process.
        """
        payload = self._request_json("GET", "retrieval/presets")
        return RetrievalPresetDiscoveryResponse.from_dict(payload)

    def delete_document(self, document_id: str) -> None:
        """
        Delete a document by identifier.

        Args:
            document_id: Document identifier to delete.
        """
        encoded_id = encode_path_component(document_id)
        self._request_no_content("DELETE", f"documents/{encoded_id}")

    def create_session(
        self,
        session_id: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> Session:
        """
        Create a new chat session.

        Args:
            session_id: Optional client-provided session identifier.
            idempotency_key: Optional ``Idempotency-Key`` header for safe retries.

        Returns:
            A typed session response.
        """
        body: JSONDict = {}
        if session_id is not None:
            body["session_id"] = session_id
        headers: JSONDict | None = None
        if idempotency_key is not None:
            if not idempotency_key.strip():
                raise ValueError("idempotency_key must not be empty.")
            headers = {"Idempotency-Key": idempotency_key.strip()}
        payload = self._request_json("POST", "sessions", json=body, headers=headers)
        return Session.from_dict(payload)

    def get_session(self, session_id: str) -> Session:
        """
        Fetch session metadata by identifier.

        Args:
            session_id: Session identifier to retrieve.

        Returns:
            A typed session response.
        """
        payload = self._request_json("GET", f"sessions/{encode_path_component(session_id)}")
        return Session.from_dict(payload)

    def get_session_history(self, session_id: str) -> SessionHistoryResponse:
        """
        Fetch chat message history for a session.

        Args:
            session_id: Session identifier to retrieve history for.

        Returns:
            A typed session history response.
        """
        encoded_id = encode_path_component(session_id)
        payload = self._request_json("GET", f"sessions/{encoded_id}/history")
        return SessionHistoryResponse.from_dict(payload)

    def list_sessions(self) -> SessionListResponse:
        """
        List all sessions for the authenticated tenant.

        Returns:
            A typed list of session responses.
        """
        payload = self._request_json("GET", "sessions")
        return SessionListResponse.from_dict(payload)

    def post_feedback(
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
        payload = self._request_json("POST", "feedback", json=body)
        return FeedbackItem.from_dict(payload)

    def list_feedback(
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
        payload = self._request_json("GET", "feedback", params=params or None)
        return FeedbackListResponse.from_dict(payload)

    def delete_session(self, session_id: str) -> None:
        """
        Delete a session by identifier.

        Args:
            session_id: Session identifier to delete.
        """
        self._request_no_content("DELETE", f"sessions/{encode_path_component(session_id)}")

    def chat(
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
        """
        Ask a question against a single document.

        Args:
            question: User question to answer.
            doc_id: Document identifier to search against.
            match_count: Number of matching chunks to retrieve.
            session_id: Optional session identifier for conversation continuity.
            scope: Retrieval scope — ``"session"`` (default) or ``"tenant"``.

        Returns:
            A typed chat response containing the answer and citations.
        """
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
        response_payload = self._request_json("POST", "chat", json=payload)
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
    ) -> Iterator[StreamChatEvent]:
        """
        Stream a chat answer as typed Server-Sent Events.

        Args:
            question: User question to answer.
            doc_id: Document identifier to search against.
            match_count: Number of matching chunks to retrieve.
            session_id: Optional session identifier for conversation continuity.
            scope: Retrieval scope — ``"session"`` (default) or ``"tenant"``.
            timeout: Optional per-request timeout override.

        Yields:
            Token and completion events from the streaming API.

        Raises:
            ChatVectorAPIError: If the stream fails before or during delivery.
        """
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

        return self._iter_stream_chat_events(request_kwargs)

    def _iter_stream_chat_events(self, request_kwargs: JSONDict) -> Iterator[StreamChatEvent]:
        """Open a streaming chat request and yield parsed SSE events."""
        try:
            with self._client.stream("POST", "chat/stream", **request_kwargs) as response:
                raise_for_stream_response(response, self._map_http_error)
                try:
                    yield from iter_stream_chat_events(
                        response.iter_lines(),
                        map_error=map_stream_error,
                    )
                finally:
                    response.close()
        except httpx.TimeoutException as exc:
            raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
        except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
        except httpx.HTTPStatusError as exc:
            raise self._map_http_error(exc.response) from exc
        except httpx.RequestError as exc:
            raise ChatVectorAPIError(
                self._msg_unexpected(), details={"error": str(exc)}
            ) from exc

    def batch_chat(
        self,
        queries: Sequence[BatchChatQuery | JSONMapping],
        session_id: str | None = None,
        scope: RetrievalScope | None = None,
        debug_retrieval: bool = False,
        retrieval: RetrievalConfig | None = None,
        history: HistoryConfig | None = None,
    ) -> BatchChatResponse:
        """
        Run multiple chat queries in a single API call.

        A batch item that names exactly one document is treated as compare-style:
        session history is not injected and successful turns are not persisted,
        even when ``session_id`` is set.

        Args:
            queries: List of batch query payloads or ``BatchChatQuery`` models.
            session_id: Optional shared session identifier for the batch.
            scope: Optional shared retrieval scope for the batch.

        Returns:
            A typed batch response containing per-query outcomes.
        """
        payload = build_batch_chat_payload(
            queries=queries,
            session_id=session_id,
            scope=scope,
            debug_retrieval=debug_retrieval,
            retrieval=retrieval,
            history=history,
        )
        response_payload = self._request_json("POST", "chat/batch", json=payload)
        return BatchChatResponse.from_dict(response_payload)

    def iter_document_status(
        self,
        document_id: str,
        timeout: float | httpx.Timeout | None = None,
    ) -> Iterator[DocumentStatus]:
        """
        Stream document ingestion status updates as typed Server-Sent Events.

        Args:
            document_id: Document identifier to monitor.
            timeout: Optional per-request timeout override.

        Yields:
            Status snapshots until the document reaches ``completed`` or ``failed``.

        Raises:
            ChatVectorAPIError: If the stream fails before or during delivery.
        """
        request_kwargs: JSONDict = {}
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        encoded_id = encode_path_component(document_id)
        return self._iter_document_status_events(encoded_id, request_kwargs)

    def _iter_document_status_events(
        self,
        document_id: str,
        request_kwargs: JSONDict,
    ) -> Iterator[DocumentStatus]:
        """Open a document status stream and yield parsed SSE events."""
        try:
            with self._client.stream(
                "GET",
                f"documents/{document_id}/status/stream",
                **request_kwargs,
            ) as response:
                raise_for_stream_response(response, self._map_http_error)
                try:
                    yield from iter_document_status_events(
                        response.iter_lines(),
                        map_error=map_document_status_stream_error,
                    )
                finally:
                    response.close()
        except httpx.TimeoutException as exc:
            raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
        except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
        except httpx.HTTPStatusError as exc:
            raise self._map_http_error(exc.response) from exc
        except httpx.RequestError as exc:
            raise ChatVectorAPIError(
                self._msg_unexpected(), details={"error": str(exc)}
            ) from exc

    def wait_for_ready(
        self,
        document_id: str,
        timeout: int = 60,
        interval: int = 2,
    ) -> DocumentStatus:
        """
        Poll the document status endpoint until ingestion completes or fails.

        Args:
            document_id: Document identifier to monitor.
            timeout: Maximum number of seconds to wait.
            interval: Number of seconds to sleep between polls.

        Returns:
            The final status payload when the document is completed.

        Raises:
            ChatVectorAPIError: If document processing reports a failed status.
            ChatVectorTimeoutError: If polling exceeds the timeout.
            ValueError: If timeout or interval are invalid.
        """
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
                last_response = self.get_status(document_id, deadline_monotonic=deadline)
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

            time.sleep(cap_duration_to_deadline(float(interval), deadline))

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

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        deadline_monotonic: float | None = None,
        **kwargs: Any,
    ) -> JSONDict:
        """
        Send an HTTP request and return the decoded JSON object response.

        Args:
            method: HTTP method to use.
            url: Relative API path.
            **kwargs: Additional request parameters passed to ``httpx.Client``.

        Returns:
            A JSON object decoded into a Python dictionary.

        Raises:
            ChatVectorAPIError: If the API or network request fails.
        """
        response = self._request_response(
            method,
            url,
            deadline_monotonic=deadline_monotonic,
            **kwargs,
        )
        return self._parse_json_dict(response)

    def _request_no_content(
        self,
        method: str,
        url: str,
        *,
        deadline_monotonic: float | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Send an HTTP request that returns no response body on success.

        Args:
            method: HTTP method to use.
            url: Relative API path.
            **kwargs: Additional request parameters passed to ``httpx.Client``.

        Raises:
            ChatVectorAPIError: If the API or network request fails.
        """
        self._request_response(
            method,
            url,
            deadline_monotonic=deadline_monotonic,
            **kwargs,
        )

    def _request_response(
        self,
        method: str,
        url: str,
        *,
        deadline_monotonic: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Send an HTTP request with retry support and return the raw response.

        Args:
            method: HTTP method to use.
            url: Relative API path.
            **kwargs: Additional request parameters passed to ``httpx.Client``.

        Returns:
            The successful HTTP response.

        Raises:
            ChatVectorAPIError: If the API or network request fails.
        """
        max_attempts = self.max_retries + 1
        call_idx = [0]
        retryable_method = is_retryable_method(method)
        request_kwargs = dict(kwargs)
        if "timeout" not in request_kwargs:
            request_kwargs["timeout"] = request_timeout_for_deadline(
                self._default_timeout,
                deadline_monotonic,
            )

        def _attempt() -> httpx.Response:
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
                response = self._client.request(method, url, **per_attempt_kwargs)
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

        return retry_sync(
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

    def _msg_invalid_api_key(self) -> str:
        """Return the standard authentication failure message."""
        from ._common import msg_invalid_api_key

        return msg_invalid_api_key()

    def _msg_rate_limit(self) -> str:
        """Return the standard rate-limit failure message."""
        from ._common import msg_rate_limit

        return msg_rate_limit()

    def _msg_timeout_or_connection(self) -> str:
        """Return the standard timeout or connection failure message."""
        return msg_timeout_or_connection()

    def _msg_unexpected(self) -> str:
        """Return the standard unexpected failure message."""
        return msg_unexpected()

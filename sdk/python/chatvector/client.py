"""Synchronous client for interacting with the ChatVector API."""

from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from .exceptions import (
    ChatVectorAPIError,
    ChatVectorAuthError,
    ChatVectorRateLimitError,
    ChatVectorTimeoutError,
)
from .models import (
    BatchChatQuery,
    BatchChatResponse,
    ChatResponse,
    DocumentResponse,
    DocumentStatus,
)

JSONDict = dict[str, Any]
JSONMapping = Mapping[str, Any]


class ChatVectorClient:
    """Convenience wrapper around the ChatVector HTTP API."""

    _RETRYABLE_STATUS_CODES = {408, 429, 502, 503, 504}

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

        normalized_base_url = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        self.base_url = normalized_base_url
        self.api_key = api_key
        self.max_retries = 2
        self.retry_backoff = 0.5
        self._client = httpx.Client(
            base_url=normalized_base_url,
            headers=headers,
            timeout=30.0,
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

    def upload_document(self, file_path: str) -> DocumentResponse:
        """
        Upload a document for ingestion.

        The SDK targets ``POST /ingest`` and transparently falls back to the
        repository's current ``POST /upload`` route when needed.

        Args:
            file_path: Path to the document on disk.

        Returns:
            A typed upload response with the new document identifier and status.

        Raises:
            FileNotFoundError: If the file does not exist.
            ChatVectorAPIError: If the API returns an error response.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Document file was not found: {file_path}")

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        endpoints = ("ingest", "upload")
        last_error: ChatVectorAPIError | None = None

        for endpoint in endpoints:
            with path.open("rb") as file_handle:
                files = {"file": (path.name, file_handle, content_type)}
                try:
                    payload = self._request_json("POST", endpoint, files=files)
                    return DocumentResponse.from_dict(payload)
                except ChatVectorAPIError as exc:
                    if endpoint == "ingest" and exc.status_code == 404:
                        last_error = exc
                        continue
                    raise

        if last_error is None:
            raise ChatVectorAPIError("Document upload failed for an unknown reason.")
        raise last_error

    def get_status(self, document_id: str) -> DocumentStatus:
        """
        Fetch the ingestion status for a document.

        Args:
            document_id: The document identifier returned by ``upload_document``.

        Returns:
            A typed document status response.
        """
        payload = self._request_json("GET", f"documents/{document_id}/status")
        return DocumentStatus.from_dict(payload)

    def chat(self, question: str, doc_id: str, match_count: int = 3) -> ChatResponse:
        """
        Ask a question against a single document.

        Args:
            question: User question to answer.
            doc_id: Document identifier to search against.
            match_count: Number of matching chunks to retrieve.

        Returns:
            A typed chat response containing the answer and citations.
        """
        payload = {
            "question": question,
            "doc_id": doc_id,
            "match_count": match_count,
        }
        response_payload = self._request_json("POST", "chat", json=payload)
        return ChatResponse.from_dict(response_payload)

    def batch_chat(
        self,
        queries: Sequence[BatchChatQuery | JSONMapping],
    ) -> BatchChatResponse:
        """
        Run multiple chat queries in a single API call.

        Args:
            queries: List of batch query payloads or ``BatchChatQuery`` models.

        Returns:
            A typed batch response containing per-query outcomes.
        """
        payload = {
            "queries": [self._serialize_batch_query(query) for query in queries],
        }
        response_payload = self._request_json("POST", "chat/batch", json=payload)
        return BatchChatResponse.from_dict(response_payload)

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
        last_response: JSONDict | None = None

        while True:
            last_response = self.get_status(document_id)
            status = last_response.status

            if status == "completed":
                return last_response

            if status == "failed":
                message = f"Document '{document_id}' processing failed."
                error_payload = last_response.error
                if isinstance(error_payload, dict):
                    error_message = error_payload.get("message")
                    if isinstance(error_message, str) and error_message:
                        message = f"{message} {error_message}"
                raise ChatVectorAPIError(message, details=last_response.to_dict())

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChatVectorTimeoutError(
                    f"Timed out after {timeout} second(s) while waiting for document "
                    f"'{document_id}' to be ready.",
                    status_code=408,
                    details=last_response.to_dict(),
                )

            time.sleep(min(interval, remaining))

    def _request_json(self, method: str, url: str, **kwargs: Any) -> JSONDict:
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
        attempts = self.max_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                response = self._client.request(method, url, **kwargs)
                if response.status_code in self._RETRYABLE_STATUS_CODES and attempt < attempts:
                    self._sleep_before_retry(attempt, response)
                    continue
                response.raise_for_status()
                return self._parse_json_dict(response)
            except httpx.TimeoutException as exc:
                if attempt < attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
            except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if attempt < attempts:
                    self._sleep_before_retry(attempt)
                    continue
                raise ChatVectorTimeoutError(self._msg_timeout_or_connection()) from exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in self._RETRYABLE_STATUS_CODES and attempt < attempts:
                    self._sleep_before_retry(attempt, exc.response)
                    continue
                raise self._map_http_error(exc.response) from exc
            except httpx.RequestError as exc:
                raise ChatVectorAPIError(self._msg_unexpected(), details={"error": str(exc)}) from exc

        raise ChatVectorAPIError(self._msg_unexpected())

    def _map_http_error(self, response: httpx.Response) -> ChatVectorAPIError:
        """
        Convert an HTTP error response into the matching ChatVector exception.

        Args:
            response: Response object that triggered ``raise_for_status``.

        Returns:
            A typed ``ChatVectorAPIError`` instance.
        """
        message, details = self._extract_error_details(response)
        error_class: type[ChatVectorAPIError] = ChatVectorAPIError

        if response.status_code in {401, 403}:
            error_class = ChatVectorAuthError
        elif response.status_code == 429:
            error_class = ChatVectorRateLimitError
        elif response.status_code in {408, 504}:
            error_class = ChatVectorTimeoutError

        return error_class(
            message,
            status_code=response.status_code,
            details=details,
            response=response,
        )

    def _extract_error_details(self, response: httpx.Response) -> tuple[str, Any | None]:
        """
        Extract a readable error message and payload from an HTTP response.

        Args:
            response: Error response from the API.

        Returns:
            A tuple containing the message and the parsed error details.
        """
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            if text:
                return text, None
            return self._default_error_message(response.status_code), None

        if not isinstance(payload, dict):
            return self._default_error_message(response.status_code), payload

        detail = payload.get("detail", payload)

        if isinstance(detail, dict):
            message = detail.get("message")
            code = detail.get("code")
            if isinstance(message, str) and message:
                if isinstance(code, str) and code:
                    return f"{message} ({code})", detail
                return message, detail

        if isinstance(detail, str) and detail:
            return detail, detail

        return self._default_error_message(response.status_code), detail

    @staticmethod
    def _parse_json_dict(response: httpx.Response) -> JSONDict:
        """Decode a response body as a JSON object."""
        try:
            payload = response.json()
        except ValueError as exc:
            raise ChatVectorAPIError(
                "ChatVector returned a non-JSON response.",
                status_code=response.status_code,
                response=response,
            ) from exc

        if not isinstance(payload, dict):
            raise ChatVectorAPIError(
                "ChatVector returned an unexpected response shape.",
                status_code=response.status_code,
                details=payload,
                response=response,
            )

        return payload

    def _default_error_message(self, status_code: int) -> str:
        """Return a classification-based fallback error message."""
        if status_code in {401, 403}:
            return self._msg_invalid_api_key()
        if status_code == 429:
            return self._msg_rate_limit()
        if status_code in {408, 504}:
            return self._msg_timeout_or_connection()
        return self._msg_unexpected()

    def _sleep_before_retry(
        self,
        attempt: int,
        response: httpx.Response | None = None,
    ) -> None:
        """Pause briefly before retrying a transient failure."""
        delay = self.retry_backoff * attempt
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            try:
                if retry_after is not None:
                    delay = max(delay, float(retry_after))
            except ValueError:
                pass
        time.sleep(delay)

    @staticmethod
    def _serialize_batch_query(query: BatchChatQuery | JSONMapping) -> JSONDict:
        """Normalize a batch query into the JSON payload expected by the API."""
        if isinstance(query, BatchChatQuery):
            return query.to_dict()
        if isinstance(query, Mapping):
            return dict(query)
        raise TypeError(
            "Each batch query must be a BatchChatQuery instance or a mapping."
        )

    @staticmethod
    def _msg_invalid_api_key() -> str:
        """Return the standard authentication failure message."""
        return "ChatVector request failed: invalid or unauthorized API key."

    @staticmethod
    def _msg_rate_limit() -> str:
        """Return the standard rate-limit failure message."""
        return "ChatVector request failed: rate limit or quota exceeded. Please try again later."

    @staticmethod
    def _msg_timeout_or_connection() -> str:
        """Return the standard timeout or connection failure message."""
        return "ChatVector request failed: the service timed out or could not be reached."

    @staticmethod
    def _msg_unexpected() -> str:
        """Return the standard unexpected failure message."""
        return "ChatVector request failed due to an unexpected error."

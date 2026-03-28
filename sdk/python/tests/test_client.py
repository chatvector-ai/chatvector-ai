"""Unit tests for the ChatVector Python SDK client."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chatvector import (  # noqa: E402
    BatchChatQuery,
    BatchChatResponse,
    ChatResponse,
    ChatVectorAPIError,
    ChatVectorAuthError,
    ChatVectorClient,
    ChatVectorRateLimitError,
    ChatVectorTimeoutError,
    DocumentResponse,
    DocumentStatus,
)


def make_response(
    status_code: int,
    *,
    method: str = "GET",
    url: str = "https://api.chatvector.test/test",
    json_data: object | None = None,
    text: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Create an ``httpx.Response`` with an attached request for testing."""
    request = httpx.Request(method, url)
    if json_data is not None:
        return httpx.Response(
            status_code=status_code,
            json=json_data,
            headers=headers,
            request=request,
        )
    return httpx.Response(
        status_code=status_code,
        text=text or "",
        headers=headers,
        request=request,
    )


class ChatVectorClientTests(unittest.TestCase):
    """Exercise the synchronous ChatVector client against mocked HTTPX calls."""

    def setUp(self) -> None:
        """Create a client for each test and close it afterward."""
        self.client = ChatVectorClient("https://api.chatvector.test", api_key="token")
        self.addCleanup(self.client.close)

    def test_upload_document_returns_document_response_and_falls_back_to_upload(self) -> None:
        """The client should try `/ingest` first and fall back to `/upload` on 404."""
        tests_dir = Path(__file__).resolve().parent
        file_path = tests_dir / "guide-test-upload.pdf"
        file_path.write_bytes(b"%PDF-1.4")

        ingest_not_found = make_response(
            404,
            method="POST",
            url="https://api.chatvector.test/ingest",
            json_data={"detail": {"message": "Not found"}},
        )
        upload_ok = make_response(
            202,
            method="POST",
            url="https://api.chatvector.test/upload",
            json_data={
                "message": "Accepted",
                "document_id": "doc-123",
                "status": "queued",
                "queue_position": 1,
                "status_endpoint": "/documents/doc-123/status",
            },
        )

        try:
            with patch.object(
                self.client._client,
                "request",
                side_effect=[ingest_not_found, upload_ok],
            ) as mock_request:
                response = self.client.upload_document(str(file_path))
        finally:
            file_path.unlink(missing_ok=True)

        self.assertIsInstance(response, DocumentResponse)
        self.assertEqual(response.document_id, "doc-123")
        self.assertEqual(response.status, "queued")
        self.assertEqual(mock_request.call_count, 2)
        self.assertEqual(mock_request.call_args_list[0].args[:2], ("POST", "ingest"))
        self.assertEqual(mock_request.call_args_list[1].args[:2], ("POST", "upload"))

    def test_get_status_returns_document_status_model(self) -> None:
        """The status endpoint should deserialize into a typed model."""
        response = make_response(
            200,
            url="https://api.chatvector.test/documents/doc-123/status",
            json_data={
                "document_id": "doc-123",
                "status": "embedding",
                "chunks": {"total": 10, "processed": 4},
                "queue_position": 2,
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            status = self.client.get_status("doc-123")

        self.assertIsInstance(status, DocumentStatus)
        self.assertEqual(status.document_id, "doc-123")
        self.assertEqual(status.status, "embedding")
        self.assertEqual(status.chunks, {"total": 10, "processed": 4})
        self.assertEqual(status.queue_position, 2)

    def test_chat_returns_typed_response_with_sources(self) -> None:
        """Single chat responses should include typed source models."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data={
                "question": "What is this document about?",
                "chunks": 2,
                "answer": "It is an onboarding guide.",
                "sources": [
                    {
                        "file_name": "guide.pdf",
                        "page_number": 1,
                        "chunk_index": 0,
                    }
                ],
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            result = self.client.chat("What is this document about?", "doc-123", match_count=2)

        self.assertIsInstance(result, ChatResponse)
        self.assertEqual(result.answer, "It is an onboarding guide.")
        self.assertEqual(len(result.sources), 1)
        self.assertEqual(result.sources[0].file_name, "guide.pdf")

    def test_batch_chat_returns_typed_batch_response(self) -> None:
        """Batch chat should accept dataclass queries and parse typed results."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat/batch",
            json_data={
                "count": 2,
                "success_count": 1,
                "failure_count": 1,
                "results": [
                    {
                        "status": "ok",
                        "question": "Summarize it.",
                        "doc_ids": ["doc-123"],
                        "chunks": 3,
                        "answer": "Summary",
                        "sources": [
                            {
                                "file_name": "guide.pdf",
                                "page_number": 2,
                                "chunk_index": 1,
                            }
                        ],
                    },
                    {
                        "status": "error",
                        "question": "What are the risks?",
                        "doc_ids": ["doc-123"],
                        "chunks": 0,
                        "error": {
                            "code": "query_processing_failed",
                            "message": "boom",
                        },
                    },
                ],
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            batch = self.client.batch_chat(
                [BatchChatQuery(question="Summarize it.", doc_ids=["doc-123"], match_count=3)]
            )

        self.assertIsInstance(batch, BatchChatResponse)
        self.assertEqual(batch.count, 2)
        self.assertEqual(batch.success_count, 1)
        self.assertEqual(batch.failure_count, 1)
        self.assertEqual(batch.results[0].answer, "Summary")
        self.assertEqual(batch.results[1].error, {"code": "query_processing_failed", "message": "boom"})

    def test_wait_for_ready_polls_until_document_is_completed(self) -> None:
        """The polling helper should stop once the document is completed."""
        queued = DocumentStatus(document_id="doc-123", status="queued")
        completed = DocumentStatus(document_id="doc-123", status="completed")

        with (
            patch.object(self.client, "get_status", side_effect=[queued, completed]) as mock_status,
            patch("chatvector.client.time.sleep", return_value=None),
        ):
            result = self.client.wait_for_ready("doc-123", timeout=10, interval=1)

        self.assertEqual(result.status, "completed")
        self.assertEqual(mock_status.call_count, 2)

    def test_wait_for_ready_raises_api_error_when_processing_fails(self) -> None:
        """The polling helper should surface failed document processing."""
        failed = DocumentStatus(
            document_id="doc-123",
            status="failed",
            error={"message": "Vectorization failed."},
        )

        with patch.object(self.client, "get_status", return_value=failed):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.wait_for_ready("doc-123", timeout=10, interval=1)

        self.assertIn("Vectorization failed.", str(exc_info.exception))

    def test_wait_for_ready_raises_timeout_error_when_deadline_is_exceeded(self) -> None:
        """The polling helper should raise a timeout once the deadline passes."""
        pending = DocumentStatus(document_id="doc-123", status="embedding")

        with (
            patch.object(self.client, "get_status", return_value=pending),
            patch("chatvector.client.time.monotonic", side_effect=[0.0, 2.0]),
        ):
            with self.assertRaises(ChatVectorTimeoutError):
                self.client.wait_for_ready("doc-123", timeout=1, interval=1)

    def test_auth_failures_raise_chatvector_auth_error(self) -> None:
        """401 and 403 responses should map to the auth-specific exception."""
        response = make_response(
            401,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data={
                "detail": {
                    "code": "unauthorized",
                    "message": "Unauthorized",
                }
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            with self.assertRaises(ChatVectorAuthError):
                self.client.chat("Hello?", "doc-123")

    def test_rate_limit_failures_raise_chatvector_rate_limit_error(self) -> None:
        """429 responses should retry and then raise the rate-limit exception."""
        responses = [
            make_response(
                429,
                url="https://api.chatvector.test/documents/doc-123/status",
                json_data={"detail": {"code": "rate_limited", "message": "Slow down"}},
                headers={"Retry-After": "0"},
            )
            for _ in range(3)
        ]

        with (
            patch.object(self.client._client, "request", side_effect=responses) as mock_request,
            patch("chatvector.client.time.sleep", return_value=None) as mock_sleep,
        ):
            with self.assertRaises(ChatVectorRateLimitError):
                self.client.get_status("doc-123")

        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_timeout_failures_raise_chatvector_timeout_error(self) -> None:
        """Timeout and connection failures should raise the timeout-specific exception."""
        timeouts = [httpx.ReadTimeout("timed out") for _ in range(3)]

        with (
            patch.object(self.client._client, "request", side_effect=timeouts) as mock_request,
            patch("chatvector.client.time.sleep", return_value=None) as mock_sleep,
        ):
            with self.assertRaises(ChatVectorTimeoutError):
                self.client.get_status("doc-123")

        self.assertEqual(mock_request.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    def test_unexpected_failures_raise_base_api_error(self) -> None:
        """Unexpected HTTP failures should fall back to the base API exception."""
        response = make_response(
            500,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data={
                "detail": {
                    "code": "internal_error",
                    "message": "Something went wrong",
                }
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.chat("Hello?", "doc-123")

        self.assertNotIsInstance(exc_info.exception, ChatVectorAuthError)
        self.assertNotIsInstance(exc_info.exception, ChatVectorRateLimitError)
        self.assertNotIsInstance(exc_info.exception, ChatVectorTimeoutError)

    def test_403_forbidden_raises_chatvector_auth_error(self) -> None:
        """403 Forbidden should map identically to 401 — both raise ChatVectorAuthError."""
        response = make_response(
            403,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data={
                "detail": {
                    "code": "forbidden",
                    "message": "Forbidden",
                }
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            with self.assertRaises(ChatVectorAuthError) as exc_info:
                self.client.chat("Hello?", "doc-123")

        self.assertEqual(exc_info.exception.status_code, 403)

    def test_408_request_timeout_raises_chatvector_timeout_error(self) -> None:
        """HTTP 408 status should map to ChatVectorTimeoutError (distinct from httpx.TimeoutException)."""
        # 408 is in _RETRYABLE_STATUS_CODES so it will retry — provide 3 responses
        responses = [
            make_response(
                408,
                method="POST",
                url="https://api.chatvector.test/chat",
                json_data={"detail": {"code": "request_timeout", "message": "Request timed out"}},
            )
            for _ in range(3)
        ]

        with (
            patch.object(self.client._client, "request", side_effect=responses),
            patch("chatvector.client.time.sleep", return_value=None),
        ):
            with self.assertRaises(ChatVectorTimeoutError) as exc_info:
                self.client.chat("Hello?", "doc-123")

        self.assertEqual(exc_info.exception.status_code, 408)

    def test_504_gateway_timeout_raises_chatvector_timeout_error(self) -> None:
        """HTTP 504 status should map to ChatVectorTimeoutError (distinct from httpx.TimeoutException)."""
        # 504 is in _RETRYABLE_STATUS_CODES so it will retry — provide 3 responses
        responses = [
            make_response(
                504,
                method="GET",
                url="https://api.chatvector.test/documents/doc-123/status",
                json_data={"detail": {"code": "gateway_timeout", "message": "Gateway timed out"}},
            )
            for _ in range(3)
        ]

        with (
            patch.object(self.client._client, "request", side_effect=responses),
            patch("chatvector.client.time.sleep", return_value=None),
        ):
            with self.assertRaises(ChatVectorTimeoutError) as exc_info:
                self.client.get_status("doc-123")

        self.assertEqual(exc_info.exception.status_code, 504)

    def test_parse_json_dict_raises_when_body_is_valid_json_but_not_a_dict(self) -> None:
        """_parse_json_dict should raise ChatVectorAPIError when the body is a JSON list, not a dict."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data=[{"answer": "unexpected list"}],
        )

        with patch.object(self.client._client, "request", return_value=response):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.chat("Hello?", "doc-123")

        self.assertNotIsInstance(exc_info.exception, ChatVectorAuthError)
        self.assertNotIsInstance(exc_info.exception, ChatVectorTimeoutError)
        self.assertIn("unexpected response shape", str(exc_info.exception))

    def test_parse_json_dict_raises_when_body_is_not_valid_json(self) -> None:
        """_parse_json_dict should raise ChatVectorAPIError when the body is not valid JSON at all."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat",
            text="this is not json at all <<<>>>",
        )

        with patch.object(self.client._client, "request", return_value=response):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.chat("Hello?", "doc-123")

        self.assertIn("non-JSON response", str(exc_info.exception))


if __name__ == "__main__":
    unittest.main()

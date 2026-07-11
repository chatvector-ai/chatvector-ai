"""Unit tests for the ChatVector Python SDK client."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from chatvector import (
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
    Session,
    SessionListResponse,
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
                        "score": 0.95,
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
        self.assertEqual(result.sources[0].score, 0.95)
        self.assertEqual(result.latency_ms, 0)
        self.assertEqual(result.model, "")

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
                                "score": 0.85,
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
                [
                    BatchChatQuery(question="Summarize it.", doc_ids=["doc-123"], match_count=3),
                    BatchChatQuery(question="What are the risks?", doc_ids=["doc-123"], match_count=3),
                ]
            )

        self.assertIsInstance(batch, BatchChatResponse)
        self.assertEqual(batch.count, 2)
        self.assertEqual(batch.success_count, 1)
        self.assertEqual(batch.failure_count, 1)
        self.assertEqual(batch.results[0].answer, "Summary")
        self.assertEqual(batch.results[1].error, {"code": "query_processing_failed", "message": "boom"})
        self.assertEqual(batch.results[0].latency_ms, 0)
        self.assertEqual(batch.results[0].model, "")

    def test_chat_response_parses_latency_and_model(self) -> None:
        """ChatResponse.from_dict must populate latency_ms and model when present."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data={
                "question": "Q?",
                "chunks": 1,
                "answer": "A.",
                "sources": [],
                "latency_ms": 312,
                "model": "gemini-2.5-flash",
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            result = self.client.chat("Q?", "doc-123")

        self.assertIsInstance(result, ChatResponse)
        self.assertEqual(result.latency_ms, 312)
        self.assertGreater(result.latency_ms, 0)
        self.assertEqual(result.model, "gemini-2.5-flash")

    def test_batch_result_parses_latency_and_model(self) -> None:
        """BatchChatResult.from_dict must populate latency_ms and model when present."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat/batch",
            json_data={
                "count": 1,
                "success_count": 1,
                "failure_count": 0,
                "results": [
                    {
                        "status": "ok",
                        "question": "Q?",
                        "doc_ids": ["doc-123"],
                        "chunks": 2,
                        "answer": "A.",
                        "sources": [],
                        "latency_ms": 789,
                        "model": "gpt-4o-mini",
                    }
                ],
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            batch = self.client.batch_chat(
                [BatchChatQuery(question="Q?", doc_ids=["doc-123"])]
            )

        self.assertEqual(batch.results[0].latency_ms, 789)
        self.assertGreater(batch.results[0].latency_ms, 0)
        self.assertEqual(batch.results[0].model, "gpt-4o-mini")

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

    def test_create_session_returns_typed_session(self) -> None:
        """Session creation should deserialize into a typed session model."""
        response = make_response(
            201,
            method="POST",
            url="https://api.chatvector.test/sessions",
            json_data={
                "id": "sess-1",
                "tenant_id": "tenant-1",
                "created_at": "2026-01-01T00:00:00",
                "last_active": "2026-01-01T00:00:00",
                "metadata": {},
                "document_ids": [],
            },
        )

        with patch.object(self.client._client, "request", return_value=response) as mock_request:
            session = self.client.create_session()

        self.assertIsInstance(session, Session)
        self.assertEqual(session.id, "sess-1")
        self.assertEqual(session.tenant_id, "tenant-1")
        self.assertEqual(session.document_ids, [])
        self.assertEqual(mock_request.call_args.kwargs["json"], {})

    def test_create_session_accepts_custom_session_id(self) -> None:
        """Session creation should forward a client-provided session identifier."""
        response = make_response(
            201,
            method="POST",
            url="https://api.chatvector.test/sessions",
            json_data={
                "id": "custom-sess",
                "tenant_id": "tenant-1",
                "created_at": "2026-01-01T00:00:00",
                "last_active": "2026-01-01T00:00:00",
                "metadata": {},
                "document_ids": [],
            },
        )

        with patch.object(self.client._client, "request", return_value=response) as mock_request:
            session = self.client.create_session(session_id="custom-sess")

        self.assertEqual(session.id, "custom-sess")
        self.assertEqual(mock_request.call_args.kwargs["json"], {"session_id": "custom-sess"})

    def test_get_session_returns_typed_session(self) -> None:
        """Fetching a session should deserialize into a typed session model."""
        response = make_response(
            200,
            url="https://api.chatvector.test/sessions/sess-1",
            json_data={
                "id": "sess-1",
                "tenant_id": "tenant-1",
                "created_at": "2026-01-01T00:00:00",
                "last_active": "2026-01-02T00:00:00",
                "metadata": {"source": "sdk"},
                "document_ids": ["doc-123"],
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            session = self.client.get_session("sess-1")

        self.assertEqual(session.id, "sess-1")
        self.assertEqual(session.metadata, {"source": "sdk"})
        self.assertEqual(session.document_ids, ["doc-123"])

    def test_list_sessions_returns_typed_list_response(self) -> None:
        """Listing sessions should deserialize into a typed list response."""
        response = make_response(
            200,
            url="https://api.chatvector.test/sessions",
            json_data={
                "sessions": [
                    {
                        "id": "sess-1",
                        "tenant_id": "tenant-1",
                        "created_at": "2026-01-01T00:00:00",
                        "last_active": "2026-01-01T00:00:00",
                        "metadata": {},
                        "document_ids": [],
                    },
                    {
                        "id": "sess-2",
                        "tenant_id": "tenant-1",
                        "created_at": "2026-01-02T00:00:00",
                        "last_active": "2026-01-02T00:00:00",
                        "metadata": {},
                        "document_ids": ["doc-456"],
                    },
                ]
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            result = self.client.list_sessions()

        self.assertIsInstance(result, SessionListResponse)
        self.assertEqual(len(result.sessions), 2)
        self.assertEqual(result.sessions[1].document_ids, ["doc-456"])

    def test_delete_session_sends_delete_request(self) -> None:
        """Deleting a session should issue a DELETE request and accept 204 responses."""
        response = make_response(
            204,
            method="DELETE",
            url="https://api.chatvector.test/sessions/sess-1",
        )

        with patch.object(self.client._client, "request", return_value=response) as mock_request:
            self.client.delete_session("sess-1")

        self.assertEqual(mock_request.call_args.args[:2], ("DELETE", "sessions/sess-1"))

    def test_get_session_not_found_raises_structured_api_error(self) -> None:
        """Missing sessions should raise a structured API error with status code 404."""
        response = make_response(
            404,
            url="https://api.chatvector.test/sessions/missing",
            json_data={"detail": "Session not found"},
        )

        with patch.object(self.client._client, "request", return_value=response):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.get_session("missing")

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertEqual(exc_info.exception.details, "Session not found")

    def test_chat_forwards_session_id_and_scope(self) -> None:
        """Single chat requests should forward session and scope parameters."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data={
                "question": "What is this document about?",
                "chunks": 1,
                "answer": "An onboarding guide.",
                "sources": [],
            },
        )

        with patch.object(self.client._client, "request", return_value=response) as mock_request:
            result = self.client.chat(
                "What is this document about?",
                "doc-123",
                session_id="sess-1",
                scope="tenant",
            )

        self.assertEqual(result.answer, "An onboarding guide.")
        self.assertEqual(
            mock_request.call_args.kwargs["json"],
            {
                "question": "What is this document about?",
                "doc_id": "doc-123",
                "match_count": 5,
                "session_id": "sess-1",
                "scope": "tenant",
            },
        )

    def test_chat_omits_session_and_scope_when_not_provided(self) -> None:
        """Single chat requests should remain backward compatible without session parameters."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data={
                "question": "Hello?",
                "chunks": 1,
                "answer": "Hi.",
                "sources": [],
            },
        )

        with patch.object(self.client._client, "request", return_value=response) as mock_request:
            self.client.chat("Hello?", "doc-123")

        self.assertEqual(
            mock_request.call_args.kwargs["json"],
            {
                "question": "Hello?",
                "doc_id": "doc-123",
                "match_count": 5,
            },
        )

    def test_batch_chat_forwards_batch_and_query_session_scope(self) -> None:
        """Batch chat should forward shared and per-query session/scope parameters."""
        response = make_response(
            200,
            method="POST",
            url="https://api.chatvector.test/chat/batch",
            json_data={
                "count": 1,
                "success_count": 1,
                "failure_count": 0,
                "results": [
                    {
                        "status": "ok",
                        "question": "Summarize it.",
                        "doc_ids": ["doc-123"],
                        "chunks": 1,
                        "answer": "Summary",
                        "sources": [],
                    }
                ],
            },
        )

        with patch.object(self.client._client, "request", return_value=response) as mock_request:
            batch = self.client.batch_chat(
                [
                    BatchChatQuery(
                        question="Summarize it.",
                        doc_ids=["doc-123"],
                        session_id="sess-item",
                        scope="tenant",
                    )
                ],
                session_id="sess-batch",
                scope="session",
            )

        self.assertEqual(batch.results[0].answer, "Summary")
        self.assertEqual(
            mock_request.call_args.kwargs["json"],
            {
                "queries": [
                    {
                        "question": "Summarize it.",
                        "doc_ids": ["doc-123"],
                        "match_count": 5,
                        "session_id": "sess-item",
                        "scope": "tenant",
                    }
                ],
                "session_id": "sess-batch",
                "scope": "session",
            },
        )

    def test_invalid_scope_raises_structured_api_error(self) -> None:
        """Validation failures for unsupported scope values should raise structured API errors."""
        response = make_response(
            422,
            method="POST",
            url="https://api.chatvector.test/chat",
            json_data={
                "detail": [
                    {
                        "type": "literal_error",
                        "loc": ["body", "scope"],
                        "msg": "Input should be 'session' or 'tenant'",
                        "input": "global",
                    }
                ]
            },
        )

        with patch.object(self.client._client, "request", return_value=response):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                self.client.chat("Hello?", "doc-123", scope="global")  # type: ignore[arg-type]

        self.assertEqual(exc_info.exception.status_code, 422)
        self.assertIsInstance(exc_info.exception.details, list)


if __name__ == "__main__":
    unittest.main()

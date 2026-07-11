"""Unit tests for streaming chat in the ChatVector Python SDK."""

from __future__ import annotations

import json
import unittest
from typing import Iterator
from unittest.mock import patch

import httpx

from chatvector import (
    ChatVectorAPIError,
    ChatVectorClient,
    ChatVectorRateLimitError,
    ChatVectorTimeoutError,
    StreamChatEvent,
)
from chatvector._sse import iter_stream_chat_events, map_stream_error
from chatvector.models import StreamErrorEvent


class MockStreamResponse:
    """Minimal streaming response double for SDK tests."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        lines: list[str] | None = None,
        json_data: object | None = None,
        text: str = "",
        close_tracker: list[bool] | None = None,
    ) -> None:
        self.status_code = status_code
        self._lines = list(lines or [])
        self._close_tracker = close_tracker
        self._json_data = json_data
        self._text = text
        self.request = httpx.Request("POST", "https://api.chatvector.test/chat/stream")

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def iter_lines(self) -> Iterator[str]:
        yield from self._lines

    @property
    def text(self) -> str:
        return self._text

    def json(self) -> object:
        if self._json_data is None:
            raise ValueError("No JSON payload configured.")
        return self._json_data

    def close(self) -> None:
        if self._close_tracker is not None:
            self._close_tracker.append(True)


class MockStreamContext:
    """Context manager wrapper around ``MockStreamResponse``."""

    def __init__(self, response: MockStreamResponse) -> None:
        self._response = response

    def __enter__(self) -> MockStreamResponse:
        return self._response

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self._response.close()


def success_sse_lines() -> list[str]:
    """Return a successful token/complete/done SSE sequence."""
    return [
        "event: token",
        'data: "Hello "',
        "",
        "event: token",
        'data: "world"',
        "",
        "event: complete",
        "data: "
        + json.dumps(
            {
                "type": "complete",
                "session_id": "sess-1",
                "sources": [
                    {
                        "file_name": "guide.pdf",
                        "page_number": 1,
                        "chunk_index": 0,
                        "score": 0.91,
                    }
                ],
                "latency_ms": 321,
                "model": "gemini-2.5-flash",
            }
        ),
        "",
        "event: done",
        "data: [DONE]",
        "",
    ]


class StreamChatTests(unittest.TestCase):
    """Exercise streaming chat parsing and client iteration."""

    def setUp(self) -> None:
        self.client = ChatVectorClient("https://api.chatvector.test", api_key="token")
        self.addCleanup(self.client.close)

    def test_iter_stream_chat_events_parses_token_and_complete(self) -> None:
        """SSE parsing should yield typed token and completion events."""
        events = list(
            iter_stream_chat_events(iter(success_sse_lines()), map_error=map_stream_error)
        )

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].type, "token")
        self.assertEqual(events[0].content, "Hello ")
        self.assertEqual(events[1].type, "token")
        self.assertEqual(events[1].content, "world")
        self.assertEqual(events[2].type, "complete")
        self.assertEqual(events[2].session_id, "sess-1")
        self.assertEqual(events[2].latency_ms, 321)
        self.assertEqual(events[2].model, "gemini-2.5-flash")
        self.assertEqual(events[2].sources[0].file_name, "guide.pdf")

    def test_iter_stream_chat_events_ignores_legacy_done(self) -> None:
        """Legacy ``done`` events should be ignored for compatibility."""
        lines = ["event: done", "data: [DONE]", ""]
        events = list(iter_stream_chat_events(iter(lines), map_error=map_stream_error))
        self.assertEqual(events, [])

    def test_map_stream_error_rate_limit(self) -> None:
        """Streaming error events should map to typed SDK exceptions."""
        error = StreamErrorEvent(code="llm_rate_limited", message="Slow down")
        exc = map_stream_error(error)
        self.assertIsInstance(exc, ChatVectorRateLimitError)

    def test_stream_chat_yields_events_from_mocked_response(self) -> None:
        """The client should expose a typed iterator over SSE events."""
        mock_response = MockStreamResponse(lines=success_sse_lines())

        with patch.object(
            self.client._client,
            "stream",
            return_value=MockStreamContext(mock_response),
        ):
            events = list(
                self.client.stream_chat("Summarize this", "doc-123", session_id="sess-1")
            )

        self.assertEqual(len(events), 3)
        self.assertIsInstance(events[0], StreamChatEvent)
        self.assertEqual(events[2].sources[0].score, 0.91)

    def test_stream_chat_forwards_session_id_scope_and_timeout(self) -> None:
        """Streaming requests should forward optional chat parameters."""
        mock_response = MockStreamResponse(lines=success_sse_lines())
        captured: dict[str, object] = {}

        def capture_stream(method: str, url: str, **kwargs: object) -> MockStreamContext:
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            return MockStreamContext(mock_response)

        with patch.object(self.client._client, "stream", side_effect=capture_stream):
            list(
                self.client.stream_chat(
                    "Question?",
                    "doc-123",
                    match_count=3,
                    session_id="sess-1",
                    scope="tenant",
                    timeout=12.5,
                )
            )

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["url"], "chat/stream")
        request_kwargs = captured["kwargs"]
        self.assertEqual(request_kwargs["timeout"], 12.5)
        self.assertEqual(
            request_kwargs["json"],
            {
                "question": "Question?",
                "doc_id": "doc-123",
                "match_count": 3,
                "session_id": "sess-1",
                "scope": "tenant",
            },
        )

    def test_stream_chat_raises_on_error_event(self) -> None:
        """Backend error events should become structured SDK exceptions."""
        lines = [
            "event: error",
            "data: "
            + json.dumps(
                {
                    "type": "error",
                    "code": "no_documents_in_scope",
                    "message": "No documents available.",
                }
            ),
            "",
        ]
        mock_response = MockStreamResponse(lines=lines)

        with patch.object(
            self.client._client,
            "stream",
            return_value=MockStreamContext(mock_response),
        ):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                list(self.client.stream_chat("Question?", "doc-123"))

        self.assertEqual(exc_info.exception.details["code"], "no_documents_in_scope")

    def test_stream_chat_raises_on_http_error(self) -> None:
        """Non-success HTTP responses should map to SDK exceptions before parsing."""
        mock_response = MockStreamResponse(
            status_code=400,
            json_data={
                "detail": {
                    "code": "streaming_disabled",
                    "message": "Streaming responses are currently disabled.",
                }
            },
            text='{"detail":{"code":"streaming_disabled","message":"Streaming responses are currently disabled."}}',
        )

        with patch.object(
            self.client._client,
            "stream",
            return_value=MockStreamContext(mock_response),
        ):
            with self.assertRaises(ChatVectorAPIError) as exc_info:
                list(self.client.stream_chat("Question?", "doc-123"))

        self.assertEqual(exc_info.exception.status_code, 400)
        self.assertIn("Streaming responses are currently disabled.", str(exc_info.exception))

    def test_stream_chat_early_termination_closes_response(self) -> None:
        """Stopping iteration early should close the underlying HTTP stream."""
        close_tracker: list[bool] = []
        mock_response = MockStreamResponse(
            lines=success_sse_lines(),
            close_tracker=close_tracker,
        )

        with patch.object(
            self.client._client,
            "stream",
            return_value=MockStreamContext(mock_response),
        ):
            iterator = self.client.stream_chat("Question?", "doc-123")
            next(iterator)
            iterator.close()

        self.assertTrue(close_tracker)

    def test_stream_chat_timeout_raises_timeout_error(self) -> None:
        """Transport timeouts should map to ChatVectorTimeoutError."""
        with patch.object(
            self.client._client,
            "stream",
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            with self.assertRaises(ChatVectorTimeoutError):
                list(self.client.stream_chat("Question?", "doc-123"))


if __name__ == "__main__":
    unittest.main()

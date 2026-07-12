import asyncio
import json
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.chat_service as chat_service_mod
from core.auth import AuthContext
from services.chat_service import answer_question_for_document
from services.chat_service import answer_questions_for_documents_batch

TEST_AUTH = AuthContext(tenant_id="dev")


def _parse_sse_event(raw: str) -> tuple[str, object]:
    lines = raw.strip().split("\n")
    event = lines[0].split(": ", 1)[1]
    data_raw = lines[1].split(": ", 1)[1]
    if data_raw == "[DONE]":
        return event, data_raw
    return event, json.loads(data_raw)


async def _passthrough_retrieval_doc_ids(**kwargs):
    return list(kwargs["requested_doc_ids"])


@pytest.fixture(autouse=True)
def _passthrough_retrieval_scope(request, monkeypatch):
    if "no_documents_in_scope" in request.node.name:
        return
    monkeypatch.setattr(
        chat_service_mod,
        "_resolve_retrieval_doc_ids",
        _passthrough_retrieval_doc_ids,
    )


@pytest.fixture(autouse=True)
def _disable_query_transformation_for_chat_tests(monkeypatch):
    monkeypatch.setattr(
        chat_service_mod.config, "QUERY_TRANSFORMATION_ENABLED", False
    )


@dataclass
class _FakeChunk:
    """Minimal ChunkMatch stand-in for unit tests."""

    id: str
    chunk_text: str
    file_name: Optional[str] = None
    page_number: Optional[int] = None
    chunk_index: Optional[int] = None
    document_id: Optional[str] = None
    similarity: Optional[float] = 0.85
    score_type: Optional[str] = "vector"


@pytest.mark.asyncio
async def test_answer_question_for_document_orchestrates_flow():
    chunks = [
        _FakeChunk(
            id="c1",
            chunk_text="chunk one",
            file_name="doc.pdf",
            page_number=1,
            chunk_index=0,
            document_id="doc-123",
        ),
        _FakeChunk(
            id="c2",
            chunk_text="chunk two",
            file_name="doc.pdf",
            page_number=2,
            chunk_index=1,
            document_id="doc-123",
        ),
    ]

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ) as mock_embeddings, patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=chunks)
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks", return_value="combined context"
    ) as mock_context, patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=("final answer", 123, "test-model")),
    ) as mock_answer:
        result = await answer_question_for_document(
                question="What is this about?",
                doc_id="doc-123",
                match_count=7,
                auth=TEST_AUTH,
        )

    assert result["question"] == "What is this about?"
    assert result["status"] == "ok"
    assert result["doc_id"] == "doc-123"
    assert result["chunks"] == 2
    assert result["answer"] == "final answer"
    assert result["latency_ms"] == 123
    assert result["model"] == "test-model"
    assert result["sources"] == [
        {"file_name": "doc.pdf", "page_number": 1, "chunk_index": 0, "score": 0.85, "score_type": "vector"},
        {"file_name": "doc.pdf", "page_number": 2, "chunk_index": 1, "score": 0.85, "score_type": "vector"},
    ]
    mock_embeddings.assert_awaited_once_with(["What is this about?"])
    mock_find.assert_awaited_once_with(
        doc_id="doc-123",
        query_embedding=[0.1, 0.2],
        match_count=7,
        session_id=None,
        query_text="What is this about?",
        tenant_id="dev",
    )
    mock_context.assert_called_once_with(chunks, session_context=None)
    mock_answer.assert_awaited_once_with("What is this about?", "combined context")


@pytest.mark.asyncio
async def test_answer_question_for_document_passes_session_id():
    """Verify that a non-None session_id reaches find_similar_chunks and history retrieval."""
    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks", return_value="combined context"
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=("final answer", 0, "test-model")),
    ), patch("db.get_session_history", new=AsyncMock(return_value=[])) as mock_history, patch(
        "db.store_chat_message", new=AsyncMock()
    ):
        await answer_question_for_document(
                question="Q",
                doc_id="doc-session",
                match_count=7,
                session_id="session-abc",
                auth=TEST_AUTH,
        )

    mock_find.assert_awaited_once_with(
        doc_id="doc-session",
        query_embedding=[0.1, 0.2],
        match_count=7,
        session_id="session-abc",
        query_text="Q",
        tenant_id="dev",
    )
    mock_history.assert_awaited_once()


@pytest.mark.asyncio
async def test_answer_question_soft_llm_error_matches_batch_error_shape():
    """When the LLM returns a soft-failure string, /chat should mirror batch: status + error."""
    from services.answer_service import LLM_MSG_RATE_LIMIT

    with patch(
        "services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])
    ), patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])), patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=(LLM_MSG_RATE_LIMIT, 0, "")),
    ):
        result = await answer_question_for_document(
            question="Q?", doc_id="doc-1", match_count=3, auth=TEST_AUTH
        )

    assert result["status"] == "error"
    assert result["error"]["code"] == "llm_rate_limited"
    assert result["error"]["message"] == LLM_MSG_RATE_LIMIT
    assert result["doc_id"] == "doc-1"


@pytest.mark.asyncio
async def test_answer_questions_for_documents_batch_processes_queries():
    queries = [
        {"question": "Q1", "doc_ids": ["doc-a", "doc-b"], "match_count": 3},
        {"question": "Q2", "doc_ids": ["doc-c"]},
    ]

    async def fake_find_similar_chunks(doc_id: str, query_embedding: list[float], match_count: int, **kwargs):
        # Same chunk_index across docs; distinct document_id so dedupe keeps one chunk per document.
        return [
            _FakeChunk(
                id=f"{doc_id}-1",
                chunk_text=f"chunk-{doc_id}-{match_count}",
                chunk_index=0,
                document_id=doc_id,
            )
        ]

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]]),
    ) as mock_embeddings, patch(
        "services.chat_service.find_similar_chunks",
        new=AsyncMock(side_effect=fake_find_similar_chunks),
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks",
        side_effect=lambda chunks, session_context=None: "|".join([c.chunk_text for c in chunks]),
    ) as mock_context, patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(side_effect=lambda question, context: (f"{question}:{context}", 50, "m")),
    ) as mock_answer:
        result = await answer_questions_for_documents_batch(queries, auth=TEST_AUTH)
    assert [item["status"] for item in result] == ["ok", "ok"]
    assert [item["question"] for item in result] == ["Q1", "Q2"]
    assert result[0]["doc_ids"] == ["doc-a", "doc-b"]
    assert result[0]["chunks"] == 2
    assert result[1]["doc_ids"] == ["doc-c"]
    assert result[1]["chunks"] == 1

    mock_embeddings.assert_awaited_once_with(["Q1", "Q2"])
    assert mock_find.await_count == 3
    assert mock_context.call_count == 2
    assert mock_answer.await_count == 2


@pytest.mark.asyncio
async def test_answer_questions_for_documents_batch_respects_retrieval_concurrency_limit():
    queries = [
        {"question": "Q1", "doc_ids": ["d1", "d2", "d3"]},
        {"question": "Q2", "doc_ids": ["d4", "d5", "d6"]},
        {"question": "Q3", "doc_ids": ["d7", "d8", "d9"]},
    ]

    active_calls = 0
    max_active_calls = 0

    async def fake_find_similar_chunks(doc_id: str, query_embedding: list[float], match_count: int, **kwargs):
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        return [
            _FakeChunk(
                id=f"{doc_id}-1",
                chunk_text=f"chunk-{doc_id}",
                document_id=doc_id,
            )
        ]

    with patch(
        "services.chat_service.config.RETRIEVAL_MAX_CONCURRENCY",
        2,
    ), patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1], [0.2], [0.3]]),
    ), patch(
        "services.chat_service.find_similar_chunks",
        new=AsyncMock(side_effect=fake_find_similar_chunks),
    ), patch(
        "services.chat_service.build_context_from_chunks",
        return_value="ctx",
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=("answer", 0, "m")),
    ):
        result = await answer_questions_for_documents_batch(queries, auth=TEST_AUTH)

    assert len(result) == 3
    assert max_active_calls <= 2


@pytest.mark.asyncio
async def test_answer_questions_for_documents_batch_returns_partial_failures():
    queries = [
        {"question": "Q1", "doc_ids": ["doc-a"]},
        {"question": "Q2", "doc_ids": ["doc-b"]},
    ]

    async def fake_generate_answer(question: str, context: str) -> tuple[str, int, str]:
        if question == "Q2":
            raise RuntimeError("LLM timeout")
        return f"{question}:{context}", 10, "m"

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1], [0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks",
        new=AsyncMock(
            side_effect=lambda doc_id, query_embedding, match_count, **kwargs: [
                _FakeChunk(id="c1", chunk_text="ctx", document_id=doc_id, chunk_index=0)
            ]
        ),
    ), patch(
        "services.chat_service.build_context_from_chunks",
        return_value="ctx",
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(side_effect=fake_generate_answer),
    ):
        result = await answer_questions_for_documents_batch(queries, auth=TEST_AUTH)

    assert len(result) == 2
    assert result[0]["status"] == "ok"
    assert result[1]["status"] == "error"
    assert result[1]["error"]["code"] == "query_processing_failed"
    assert result[1]["error"]["message"] == "An error occurred processing this query."
    assert "LLM timeout" not in result[1]["error"]["message"]


@pytest.mark.asyncio
async def test_answer_questions_for_documents_batch_rejects_duplicate_doc_ids():
    queries = [
        {"question": "Q1", "doc_ids": ["doc-a", "doc-a"]},
    ]

    try:
        await answer_questions_for_documents_batch(queries, auth=TEST_AUTH)
        raise AssertionError("Expected ValueError was not raised")
    except ValueError as exc:
        assert "duplicate doc IDs" in str(exc)


# ---------------------------------------------------------------------------
# Source citation tests (Issue #26)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_question_for_document_includes_sources_with_correct_shape():
    chunks = [
        _FakeChunk(
            id="c1",
            chunk_text="text a",
            file_name="report.pdf",
            page_number=3,
            chunk_index=0,
            document_id="doc-1",
        ),
        _FakeChunk(
            id="c2",
            chunk_text="text b",
            file_name="report.pdf",
            page_number=5,
            chunk_index=1,
            document_id="doc-1",
        ),
    ]

    with patch(
        "services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=chunks)
    ), patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=("ans", 0, "m")),
    ):
        result = await answer_question_for_document(
            question="Q?", doc_id="doc-1", auth=TEST_AUTH
        )

    assert "sources" in result
    assert result["status"] == "ok"
    assert result["doc_id"] == "doc-1"
    assert result["sources"] == [
        {"file_name": "report.pdf", "page_number": 3, "chunk_index": 0, "score": 0.85, "score_type": "vector"},
        {"file_name": "report.pdf", "page_number": 5, "chunk_index": 1, "score": 0.85, "score_type": "vector"},
    ]


@pytest.mark.asyncio
async def test_answer_question_for_document_sources_none_fields_for_txt():
    chunks = [
        _FakeChunk(
            id="c1",
            chunk_text="plain text",
            file_name="notes.txt",
            page_number=None,
            chunk_index=0,
            document_id="doc-txt",
        ),
    ]

    with patch(
        "services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=chunks)
    ), patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=("ans", 0, "m")),
    ):
        result = await answer_question_for_document(
            question="Q?", doc_id="doc-txt", auth=TEST_AUTH
        )

    assert result["status"] == "ok"
    assert result["doc_id"] == "doc-txt"
    assert result["sources"] == [
        {"file_name": "notes.txt", "page_number": None, "chunk_index": 0, "score": 0.85, "score_type": "vector"},
    ]


@pytest.mark.asyncio
async def test_batch_answer_includes_sources_in_ok_responses():
    queries = [{"question": "Q1", "doc_ids": ["doc-a"]}]

    chunks = [
        _FakeChunk(
            id="c1",
            chunk_text="ctx",
            file_name="slides.pdf",
            page_number=2,
            chunk_index=0,
            document_id="doc-a",
        ),
    ]

    with patch(
        "services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=chunks)
    ), patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=("answer", 0, "m")),
    ):
        result = await answer_questions_for_documents_batch(queries, auth=TEST_AUTH)

    assert result[0]["status"] == "ok"
    assert result[0]["sources"] == [
        {"file_name": "slides.pdf", "page_number": 2, "chunk_index": 0, "score": 0.85, "score_type": "vector"},
    ]


@pytest.mark.asyncio
async def test_batch_soft_llm_error_uses_same_error_codes_as_single_chat():
    from services.answer_service import LLM_MSG_MISSING_API_KEY

    queries = [{"question": "Q1", "doc_ids": ["doc-a"]}]

    with patch(
        "services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])
    ), patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])), patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=(LLM_MSG_MISSING_API_KEY, 0, "")),
    ):
        result = await answer_questions_for_documents_batch(queries, auth=TEST_AUTH)

    assert result[0]["status"] == "error"
    assert result[0]["error"]["code"] == "llm_missing_api_key"
    assert "sources" in result[0]

@pytest.mark.asyncio
async def test_answer_question_stream_for_document_success():
    """Test successful generation of an SSE stream."""
    from services.chat_service import answer_question_stream_for_document
    from core.auth import AuthContext

    async def mock_generate_stream(q, c):
        yield "part1 "
        yield "part2"

    mock_provider = MagicMock()
    mock_provider.model_name = "test-stream-model"

    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service.transform_query", new=AsyncMock(return_value=["q"])),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="context"),
        patch("services.chat_service.generate_answer_stream", new=mock_generate_stream),
        patch("services.providers.get_llm_provider", return_value=mock_provider),
    ):
        chunks = []
        async for chunk in answer_question_stream_for_document(
            "q", "doc-1", match_count=5, auth=AuthContext(tenant_id="dev")
        ):
            chunks.append(chunk)

        assert len(chunks) == 4
        assert chunks[0] == 'event: token\ndata: "part1 "\n\n'
        assert chunks[1] == 'event: token\ndata: "part2"\n\n'

        complete_event, complete_data = _parse_sse_event(chunks[2])
        assert complete_event == "complete"
        assert complete_data["type"] == "complete"
        assert complete_data["session_id"] is None
        assert complete_data["sources"] == []
        assert complete_data["latency_ms"] >= 0
        assert complete_data["model"] == "test-stream-model"

        assert chunks[3] == "event: done\ndata: [DONE]\n\n"

@pytest.mark.asyncio
async def test_stream_history_loaded_and_bounded_before_transform():
    """Streaming path must pass a bounded history slice to transform_query."""
    from services.chat_service import answer_question_stream_for_document

    window = 3
    full_history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    captured: dict = {}

    async def fake_transform(question: str, history=None) -> list[str]:
        captured["history"] = history
        return [question]

    async def mock_stream(q, c):
        yield "tok"

    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service.config.QUERY_TRANSFORMATION_HISTORY_WINDOW", window),
        patch("services.chat_service.transform_query", new=fake_transform),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer_stream", new=mock_stream),
        patch("db.get_session_history", new=AsyncMock(return_value=full_history)),
        patch("db.store_chat_message", new=AsyncMock()),
    ):
        async for _ in answer_question_stream_for_document(
            "follow-up?", "doc-1", match_count=5,
            session_id="sess-s", auth=TEST_AUTH,
        ):
            pass

    assert captured["history"] == full_history[:window]


@pytest.mark.asyncio
async def test_answer_question_stream_for_document_error():
    """Test error handling in SSE stream."""
    from services.chat_service import answer_question_stream_for_document
    from core.auth import AuthContext
    from services.answer_service import LLM_MSG_RATE_LIMIT

    async def mock_generate_stream(q, c):
        yield LLM_MSG_RATE_LIMIT

    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service.transform_query", new=AsyncMock(return_value=["q"])),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="context"),
        patch("services.chat_service.generate_answer_stream", new=mock_generate_stream),
        patch("db.store_chat_message", new=AsyncMock()) as mock_store,
    ):
        chunks = []
        async for chunk in answer_question_stream_for_document(
            "q", "doc-1", match_count=5, auth=AuthContext(tenant_id="dev"), session_id="sess-1"
        ):
            chunks.append(chunk)

        assert len(chunks) == 1
        event, data = _parse_sse_event(chunks[0])
        assert event == "error"
        assert data == {
            "type": "error",
            "code": "llm_rate_limited",
            "message": LLM_MSG_RATE_LIMIT,
        }
        mock_store.assert_not_awaited()


# ---------------------------------------------------------------------------
# Streaming SSE contract (Issue #338)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_complete_event_includes_sources_and_session_id():
    from services.chat_service import answer_question_stream_for_document

    chunks_data = [
        _FakeChunk(
            id="c1",
            chunk_text="ctx",
            file_name="report.pdf",
            page_number=3,
            chunk_index=0,
            document_id="doc-1",
        ),
    ]

    async def mock_generate_stream(q, c):
        yield "answer"

    mock_provider = MagicMock()
    mock_provider.model_name = "gemini-test"

    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service.transform_query", new=AsyncMock(return_value=["q"])),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=chunks_data),
        ),
        patch("services.chat_service.build_context_from_chunks", return_value="context"),
        patch("services.chat_service.generate_answer_stream", new=mock_generate_stream),
        patch("services.providers.get_llm_provider", return_value=mock_provider),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch("db.store_chat_message", new=AsyncMock()),
    ):
        events = []
        async for event in answer_question_stream_for_document(
            "Q?",
            "doc-1",
            session_id="sess-complete",
            auth=TEST_AUTH,
        ):
            events.append(event)

    _, complete_data = _parse_sse_event(events[-2])
    assert complete_data["session_id"] == "sess-complete"
    assert complete_data["sources"] == [
        {
            "file_name": "report.pdf",
            "page_number": 3,
            "chunk_index": 0,
            "score": 0.85,
            "score_type": "vector",
        }
    ]
    assert complete_data["model"] == "gemini-test"
    assert complete_data["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_stream_no_documents_error_is_structured_json():
    from services.chat_service import answer_question_stream_for_document

    with patch(
        "services.chat_service._resolve_retrieval_doc_ids",
        new=AsyncMock(return_value=[]),
    ):
        events = [
            event
            async for event in answer_question_stream_for_document(
                "Q?", "doc-1", auth=TEST_AUTH
            )
        ]

    assert len(events) == 1
    event_name, data = _parse_sse_event(events[0])
    assert event_name == "error"
    assert data == {
        "type": "error",
        "code": "no_documents_in_scope",
        "message": "No documents available for retrieval in the requested scope.",
    }


@pytest.mark.asyncio
async def test_stream_cancellation_does_not_persist():
    from services.chat_service import answer_question_stream_for_document

    async def blocking_stream(q, c):
        yield "partial "
        await asyncio.Event().wait()

    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service.transform_query", new=AsyncMock(return_value=["q"])),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="context"),
        patch("services.chat_service.generate_answer_stream", new=blocking_stream),
        patch("db.store_chat_message", new=AsyncMock()) as mock_store,
    ):
        gen = answer_question_stream_for_document(
            "Q?", "doc-1", session_id="sess-cancel", auth=TEST_AUTH
        )
        first = await gen.__anext__()
        assert first.startswith("event: token")
        await gen.aclose()

    mock_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_legacy_done_follows_complete_event():
    from services.chat_service import answer_question_stream_for_document

    async def mock_generate_stream(q, c):
        yield "ok"

    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service.transform_query", new=AsyncMock(return_value=["q"])),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="context"),
        patch("services.chat_service.generate_answer_stream", new=mock_generate_stream),
        patch("services.providers.get_llm_provider", return_value=MagicMock(model_name="m")),
    ):
        events = [
            event
            async for event in answer_question_stream_for_document("Q?", "doc-1", auth=TEST_AUTH)
        ]

    event_names = [_parse_sse_event(event)[0] for event in events]
    assert event_names == ["token", "complete", "done"]


# ---------------------------------------------------------------------------
# latency_ms and model fields (Issue #325)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_question_for_document_includes_latency_and_model():
    """latency_ms and model must be present and valid on a successful /chat response."""
    with patch(
        "services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ), patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(return_value=("the answer", 456, "gemini-2.5-flash")),
    ):
        result = await answer_question_for_document(
            question="Q?", doc_id="doc-1", auth=TEST_AUTH
        )

    assert result["status"] == "ok"
    assert result["latency_ms"] == 456
    assert result["latency_ms"] > 0
    assert result["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_batch_includes_latency_and_model_per_query():
    """Each batch result must carry its own latency_ms and model, not a shared total."""
    queries = [
        {"question": "Q1", "doc_ids": ["doc-a"]},
        {"question": "Q2", "doc_ids": ["doc-b"]},
    ]

    # Map question → deterministic (latency, model) so we can verify each result
    # received its own values regardless of asyncio.gather execution order.
    per_question = {
        "Q1": (100, "model-q1"),
        "Q2": (200, "model-q2"),
    }

    async def fake_generate(question: str, context: str) -> tuple[str, int, str]:
        latency, model = per_question[question]
        return f"answer-{question}", latency, model

    with patch(
        "services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1], [0.2]])
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ), patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer", new=AsyncMock(side_effect=fake_generate)
    ):
        result = await answer_questions_for_documents_batch(queries, auth=TEST_AUTH)

    assert len(result) == 2
    by_question = {item["question"]: item for item in result}
    assert by_question["Q1"]["latency_ms"] == 100
    assert by_question["Q1"]["model"] == "model-q1"
    assert by_question["Q2"]["latency_ms"] == 200
    assert by_question["Q2"]["model"] == "model-q2"
    # Values are distinct — each result reflects its own LLM call, not a shared total.
    assert by_question["Q1"]["latency_ms"] != by_question["Q2"]["latency_ms"]


@pytest.mark.asyncio
async def test_latency_and_model_present_in_no_documents_in_scope_error():
    """latency_ms and model must be present even when retrieval scope returns no docs."""
    import services.session_service as session_svc
    from core.auth import AuthContext

    session = session_svc.create_session(tenant_id="tenant-x")
    session_svc.register_session_document(session.id, "doc-allowed", "tenant-x")

    try:
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-not-in-scope",
            session_id=session.id,
            auth=AuthContext(tenant_id="tenant-x"),
            scope="session",
        )
    finally:
        session_svc._SESSIONS.pop(session.id, None)

    assert result["status"] == "error"
    assert result["error"]["code"] == "no_documents_in_scope"
    assert "latency_ms" in result
    assert "model" in result
    assert result["latency_ms"] == 0
    assert result["model"] == ""


@pytest.mark.asyncio
async def test_batch_latency_and_model_present_in_no_documents_in_scope_error():
    """Batch no_documents_in_scope results must include latency_ms and model."""
    import services.session_service as session_svc
    from core.auth import AuthContext

    session = session_svc.create_session(tenant_id="tenant-y")
    session_svc.register_session_document(session.id, "doc-allowed", "tenant-y")

    queries = [
        {
            "question": "Q?",
            "doc_ids": ["doc-not-in-scope"],
            "match_count": 5,
            "session_id": session.id,
            "scope": "session",
        }
    ]

    try:
        with patch(
            "services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])
        ):
            result = await answer_questions_for_documents_batch(
                queries,
                auth=AuthContext(tenant_id="tenant-y"),
            )
    finally:
        session_svc._SESSIONS.pop(session.id, None)

    assert result[0]["status"] == "error"
    assert result[0]["error"]["code"] == "no_documents_in_scope"
    assert "latency_ms" in result[0]
    assert "model" in result[0]
    assert result[0]["latency_ms"] == 0
    assert result[0]["model"] == ""


# ---------------------------------------------------------------------------
# History-aware retrieval (Issue #337)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_loaded_before_transform_query_for_single_chat():
    """Session history must be passed to transform_query so follow-ups can be resolved."""
    full_history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]

    captured: dict = {}

    async def fake_transform(question: str, history=None) -> list[str]:
        captured["history"] = history
        return [question]

    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("db.get_session_history", new=AsyncMock(return_value=full_history)),
        patch("db.store_chat_message", new=AsyncMock()),
        patch("services.chat_service.transform_query", new=fake_transform),
    ):
        await answer_question_for_document(
            question="What about it?",
            doc_id="doc-1",
            session_id="sess-abc",
            auth=TEST_AUTH,
        )

    assert captured["history"] is not None
    assert len(captured["history"]) <= chat_service_mod.config.QUERY_TRANSFORMATION_HISTORY_WINDOW


@pytest.mark.asyncio
async def test_history_bounded_to_window_for_single_chat():
    """Only the most recent QUERY_TRANSFORMATION_HISTORY_WINDOW messages must be passed."""
    window = 4
    full_history = [{"role": "user", "content": f"msg{i}"} for i in range(20)]

    captured: dict = {}

    async def fake_transform(question: str, history=None) -> list[str]:
        captured["history"] = history
        return [question]

    with (
        patch("services.chat_service.config.QUERY_TRANSFORMATION_HISTORY_WINDOW", window),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("db.get_session_history", new=AsyncMock(return_value=full_history)),
        patch("db.store_chat_message", new=AsyncMock()),
        patch("services.chat_service.transform_query", new=fake_transform),
    ):
        await answer_question_for_document(
            question="Q?",
            doc_id="doc-1",
            session_id="sess-abc",
            auth=TEST_AUTH,
        )

    assert captured["history"] == full_history[:window]


@pytest.mark.asyncio
async def test_no_history_passed_to_transform_when_no_session_id():
    """Without a session_id, transform_query must receive no history (one-shot behavior)."""
    captured: dict = {}

    async def fake_transform(question: str, history=None) -> list[str]:
        captured["history"] = history
        return [question]

    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("services.chat_service.transform_query", new=fake_transform),
    ):
        await answer_question_for_document(
            question="standalone question",
            doc_id="doc-1",
            auth=TEST_AUTH,
        )

    assert not captured["history"]


@pytest.mark.asyncio
async def test_history_session_isolation_single_chat():
    """get_session_history must be called with the exact session_id of the request."""
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("db.get_session_history", new=AsyncMock(return_value=[])) as mock_hist,
        patch("db.store_chat_message", new=AsyncMock()),
    ):
        await answer_question_for_document(
            question="Q",
            doc_id="doc-1",
            session_id="session-xyz",
            auth=TEST_AUTH,
        )

    mock_hist.assert_awaited_once()
    call_kwargs = mock_hist.call_args.kwargs
    assert call_kwargs["session_id"] == "session-xyz"


@pytest.mark.asyncio
async def test_history_tenant_isolation_single_chat():
    """get_session_history must be called with the tenant_id from the AuthContext."""
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("db.get_session_history", new=AsyncMock(return_value=[])) as mock_hist,
        patch("db.store_chat_message", new=AsyncMock()),
    ):
        await answer_question_for_document(
            question="Q",
            doc_id="doc-1",
            session_id="session-abc",
            auth=AuthContext(tenant_id="tenant-isolated"),
        )

    call_kwargs = mock_hist.call_args.kwargs
    assert call_kwargs["tenant_id"] == "tenant-isolated"


@pytest.mark.asyncio
async def test_batch_history_bounded_to_window():
    """In batch mode, each query's transformation history must also be bounded."""
    window = 3
    full_history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]

    captured_per_question: dict[str, list | None] = {}

    async def fake_transform(question: str, history=None) -> list[str]:
        captured_per_question[question] = history
        return [question]

    with (
        patch("services.chat_service.config.QUERY_TRANSFORMATION_HISTORY_WINDOW", window),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1], [0.2]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("db.get_session_history", new=AsyncMock(return_value=full_history)),
        patch("db.store_chat_message", new=AsyncMock()),
        patch("services.chat_service.transform_query", new=fake_transform),
    ):
        await answer_questions_for_documents_batch(
            [
                {"question": "Q1", "doc_ids": ["doc-a"], "session_id": "sess-1"},
                {"question": "Q2", "doc_ids": ["doc-b"], "session_id": "sess-2"},
            ],
            auth=TEST_AUTH,
        )

    for hist in captured_per_question.values():
        assert hist is not None
        assert len(hist) == window


@pytest.mark.asyncio
async def test_batch_no_history_for_queries_without_session_id():
    """Batch queries without session_id must receive None history for transformation."""
    captured: dict[str, list | None] = {}

    async def fake_transform(question: str, history=None) -> list[str]:
        captured[question] = history
        return [question]

    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("services.chat_service.transform_query", new=fake_transform),
    ):
        await answer_questions_for_documents_batch(
            [{"question": "standalone Q", "doc_ids": ["doc-a"]}],
            auth=TEST_AUTH,
        )

    assert not captured["standalone Q"]


@pytest.mark.asyncio
async def test_batch_history_tenant_isolation():
    """Each batch query's history load must use the tenant_id from the AuthContext."""
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("db.get_session_history", new=AsyncMock(return_value=[])) as mock_hist,
        patch("db.store_chat_message", new=AsyncMock()),
    ):
        await answer_questions_for_documents_batch(
            [{"question": "Q", "doc_ids": ["doc-a"], "session_id": "sess-t"}],
            auth=AuthContext(tenant_id="tenant-batch"),
        )

    mock_hist.assert_awaited()
    call_kwargs = mock_hist.call_args.kwargs
    assert call_kwargs["tenant_id"] == "tenant-batch"


# ---------------------------------------------------------------------------
# Compare batch session isolation (Issue #345)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_batch_ignores_polluted_session_history_in_llm_context():
    """Compare items must answer from retrieved chunks only, not prior session turns."""
    polluted_history = [
        {"role": "user", "content": "What is the PTO policy?"},
        {
            "role": "assistant",
            "content": "Employees receive 15 days of paid time off annually.",
        },
    ]
    sales_chunks = [
        _FakeChunk(
            id="c1",
            chunk_text="NexaCorp client accounts include Apex Manufacturing.",
            file_name="nexacorp3.txt",
            page_number=1,
            chunk_index=0,
            document_id="sales-doc",
        ),
    ]
    captured_contexts: list[str] = []

    async def capture_generate(question, context):
        captured_contexts.append(context)
        return ("Client account info.", 50, "test-model")

    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=sales_chunks),
        ),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(side_effect=capture_generate),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=polluted_history)),
        patch("db.store_chat_message", new=AsyncMock()) as mock_store,
    ):
        await answer_questions_for_documents_batch(
            [
                {
                    "question": "What is the PTO policy?",
                    "doc_ids": ["sales-doc"],
                    "session_id": "sess-polluted",
                }
            ],
            auth=TEST_AUTH,
        )

    assert len(captured_contexts) == 1
    context = captured_contexts[0]
    assert "[Session History]" not in context
    assert "paid time off" not in context.lower()
    assert "Apex Manufacturing" in context
    mock_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesize_batch_still_injects_session_history_into_llm_context():
    """Multi-document batch items may still use session history for context."""
    history = [{"role": "assistant", "content": "Prior synthesized answer."}]
    chunks = [
        _FakeChunk(
            id="c1",
            chunk_text="Cross-document context.",
            file_name="a.pdf",
            page_number=1,
            chunk_index=0,
            document_id="doc-a",
        ),
    ]
    captured_contexts: list[str] = []

    async def capture_generate(question, context):
        captured_contexts.append(context)
        return ("combined answer", 40, "test-model")

    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=chunks),
        ),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(side_effect=capture_generate),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=history)),
        patch("db.store_chat_message", new=AsyncMock()) as mock_store,
    ):
        await answer_questions_for_documents_batch(
            [
                {
                    "question": "Summarize across docs",
                    "doc_ids": ["doc-a", "doc-b"],
                    "session_id": "sess-synth",
                }
            ],
            auth=TEST_AUTH,
        )

    assert len(captured_contexts) == 1
    context = captured_contexts[0]
    assert "[Session History]" in context
    assert "Prior synthesized answer." in context
    assert mock_store.await_count == 2


@pytest.mark.asyncio
async def test_single_chat_still_uses_session_history_with_polluted_context():
    """Regression: regular /chat multi-turn behavior is unchanged."""
    polluted_history = [
        {"role": "assistant", "content": "Earlier handbook answer about PTO."},
    ]
    doc_chunks = [
        _FakeChunk(
            id="c1",
            chunk_text="Sales reference content.",
            file_name="sales.txt",
            page_number=1,
            chunk_index=0,
            document_id="doc-1",
        ),
    ]
    captured_contexts: list[str] = []

    async def capture_generate(question, context):
        captured_contexts.append(context)
        return ("answer", 30, "test-model")

    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=doc_chunks),
        ),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(side_effect=capture_generate),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=polluted_history)),
        patch("db.store_chat_message", new=AsyncMock()) as mock_store,
    ):
        await answer_question_for_document(
            question="Follow-up question",
            doc_id="doc-1",
            session_id="sess-chat",
            auth=TEST_AUTH,
        )

    assert len(captured_contexts) == 1
    assert "[Session History]" in captured_contexts[0]
    assert "Earlier handbook answer about PTO." in captured_contexts[0]
    assert mock_store.await_count == 2

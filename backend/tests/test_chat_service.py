import asyncio
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

import services.chat_service as chat_service_mod
from services.chat_service import answer_question_for_document
from services.chat_service import answer_questions_for_documents_batch


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


def test_answer_question_for_document_orchestrates_flow():
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
        "services.chat_service.generate_answer", new=AsyncMock(return_value="final answer")
    ) as mock_answer:
        result = asyncio.run(
            answer_question_for_document(
                question="What is this about?",
                doc_id="doc-123",
                match_count=7,
            )
        )

    assert result["question"] == "What is this about?"
    assert result["chunks"] == 2
    assert result["answer"] == "final answer"
    assert result["sources"] == [
        {"file_name": "doc.pdf", "page_number": 1, "chunk_index": 0},
        {"file_name": "doc.pdf", "page_number": 2, "chunk_index": 1},
    ]
    mock_embeddings.assert_awaited_once_with(["What is this about?"])
    mock_find.assert_awaited_once_with(
        doc_id="doc-123",
        query_embedding=[0.1, 0.2],
        match_count=7,
    )
    mock_context.assert_called_once_with(chunks)
    mock_answer.assert_awaited_once_with("What is this about?", "combined context")


def test_answer_questions_for_documents_batch_processes_queries():
    queries = [
        {"question": "Q1", "doc_ids": ["doc-a", "doc-b"], "match_count": 3},
        {"question": "Q2", "doc_ids": ["doc-c"]},
    ]

    async def fake_find_similar_chunks(doc_id: str, query_embedding: list[float], match_count: int):
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
        side_effect=lambda chunks: "|".join([c.chunk_text for c in chunks]),
    ) as mock_context, patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(side_effect=lambda question, context: f"{question}:{context}"),
    ) as mock_answer:
        result = asyncio.run(answer_questions_for_documents_batch(queries))

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


def test_answer_questions_for_documents_batch_respects_retrieval_concurrency_limit():
    queries = [
        {"question": "Q1", "doc_ids": ["d1", "d2", "d3"]},
        {"question": "Q2", "doc_ids": ["d4", "d5", "d6"]},
        {"question": "Q3", "doc_ids": ["d7", "d8", "d9"]},
    ]

    active_calls = 0
    max_active_calls = 0

    async def fake_find_similar_chunks(doc_id: str, query_embedding: list[float], match_count: int):
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
        new=AsyncMock(return_value="answer"),
    ):
        result = asyncio.run(answer_questions_for_documents_batch(queries))

    assert len(result) == 3
    assert max_active_calls <= 2


def test_answer_questions_for_documents_batch_returns_partial_failures():
    queries = [
        {"question": "Q1", "doc_ids": ["doc-a"]},
        {"question": "Q2", "doc_ids": ["doc-b"]},
    ]

    async def fake_generate_answer(question: str, context: str) -> str:
        if question == "Q2":
            raise RuntimeError("LLM timeout")
        return f"{question}:{context}"

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1], [0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks",
        new=AsyncMock(
            side_effect=lambda doc_id, query_embedding, match_count: [
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
        result = asyncio.run(answer_questions_for_documents_batch(queries))

    assert len(result) == 2
    assert result[0]["status"] == "ok"
    assert result[1]["status"] == "error"
    assert result[1]["error"]["code"] == "query_processing_failed"


def test_answer_questions_for_documents_batch_rejects_duplicate_doc_ids():
    queries = [
        {"question": "Q1", "doc_ids": ["doc-a", "doc-a"]},
    ]

    try:
        asyncio.run(answer_questions_for_documents_batch(queries))
        raise AssertionError("Expected ValueError was not raised")
    except ValueError as exc:
        assert "duplicate doc IDs" in str(exc)


# ---------------------------------------------------------------------------
# Source citation tests (Issue #26)
# ---------------------------------------------------------------------------


def test_answer_question_for_document_includes_sources_with_correct_shape():
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
        "services.chat_service.generate_answer", new=AsyncMock(return_value="ans")
    ):
        result = asyncio.run(answer_question_for_document(question="Q?", doc_id="doc-1"))

    assert "sources" in result
    assert result["sources"] == [
        {"file_name": "report.pdf", "page_number": 3, "chunk_index": 0},
        {"file_name": "report.pdf", "page_number": 5, "chunk_index": 1},
    ]


def test_answer_question_for_document_sources_none_fields_for_txt():
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
        "services.chat_service.generate_answer", new=AsyncMock(return_value="ans")
    ):
        result = asyncio.run(answer_question_for_document(question="Q?", doc_id="doc-txt"))

    assert result["sources"] == [
        {"file_name": "notes.txt", "page_number": None, "chunk_index": 0},
    ]


def test_batch_answer_includes_sources_in_ok_responses():
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
        "services.chat_service.generate_answer", new=AsyncMock(return_value="answer")
    ):
        result = asyncio.run(answer_questions_for_documents_batch(queries))

    assert result[0]["status"] == "ok"
    assert result[0]["sources"] == [
        {"file_name": "slides.pdf", "page_number": 2, "chunk_index": 0},
    ]

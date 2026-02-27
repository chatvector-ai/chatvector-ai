import asyncio
from unittest.mock import AsyncMock, patch

from services.chat_service import answer_question_for_document
from services.chat_service import answer_questions_for_documents_batch


def test_answer_question_for_document_orchestrates_flow():
    chunks = [{"id": "c1", "chunk_text": "chunk one"}, {"id": "c2", "chunk_text": "chunk two"}]

    with patch("services.chat_service.get_embedding", new=AsyncMock(return_value=[0.1, 0.2])) as mock_embedding, patch(
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

    assert result == {
        "question": "What is this about?",
        "chunks": 2,
        "answer": "final answer",
    }
    mock_embedding.assert_awaited_once_with("What is this about?")
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
        return [{"id": f"{doc_id}-1", "chunk_text": f"chunk-{doc_id}-{match_count}"}]

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]]),
    ) as mock_embeddings, patch(
        "services.chat_service.find_similar_chunks",
        new=AsyncMock(side_effect=fake_find_similar_chunks),
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks",
        side_effect=lambda chunks: "|".join([c["chunk_text"] for c in chunks]),
    ) as mock_context, patch(
        "services.chat_service.generate_answer",
        new=AsyncMock(side_effect=lambda question, context: f"{question}:{context}"),
    ) as mock_answer:
        result = asyncio.run(answer_questions_for_documents_batch(queries))

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
        return [{"id": f"{doc_id}-1", "chunk_text": f"chunk-{doc_id}"}]

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

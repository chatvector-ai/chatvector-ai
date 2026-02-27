import asyncio
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("supabase")

from db.supabase_service import SupabaseService


class _FakeResult:
    def __init__(self, data):
        self.data = data


def test_run_io_uses_asyncio_to_thread():
    service = SupabaseService()
    calls = {"count": 0}

    async def fake_to_thread(operation):
        calls["count"] += 1
        return operation()

    with patch("db.supabase_service.asyncio.to_thread", side_effect=fake_to_thread):
        result = asyncio.run(service._run_io(lambda: "ok"))

    assert result == "ok"
    assert calls["count"] == 1


def test_create_document_uses_async_io_wrapper():
    service = SupabaseService()
    mock_run_io = AsyncMock(return_value=_FakeResult([{"id": "doc-123"}]))

    with patch.object(service, "_run_io", mock_run_io):
        doc_id = asyncio.run(service.create_document("example.pdf"))

    assert doc_id == "doc-123"
    mock_run_io.assert_awaited_once()


def test_find_similar_chunks_uses_async_io_wrapper_and_maps_payload():
    service = SupabaseService()
    mock_run_io = AsyncMock(
        return_value=_FakeResult(
            [
                {
                    "id": "chunk-1",
                    "chunk_text": "hello",
                    "similarity": 0.99,
                }
            ]
        )
    )

    with patch.object(service, "_run_io", mock_run_io):
        matches = asyncio.run(
            service.find_similar_chunks(
                doc_id="doc-7",
                query_embedding=[0.1, 0.2],
                match_count=4,
            )
        )

    assert len(matches) == 1
    assert matches[0].id == "chunk-1"
    assert matches[0].document_id == "doc-7"
    assert matches[0].chunk_text == "hello"
    assert matches[0].similarity == 0.99
    mock_run_io.assert_awaited_once()

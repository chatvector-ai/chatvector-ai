import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest

pytest.importorskip("pgvector")

from db.sqlalchemy_service import SQLAlchemyService


class _FakeChunk:
    def __init__(self, chunk_id: str, doc_id: str):
        self.id = chunk_id
        self.chunk_text = "chunk"
        self.document_id = doc_id
        self.embedding = [0.1, 0.2]
        self.created_at = datetime.utcnow()


class _FakeResult:
    def __init__(self, chunks):
        self._chunks = chunks

    def scalars(self):
        return self

    def all(self):
        return self._chunks


class _FakeSession:
    def __init__(self, on_execute):
        self._on_execute = on_execute

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *args, **kwargs):
        return await self._on_execute()


@pytest.mark.asyncio
async def test_find_similar_chunks_respects_service_retrieval_limit():
    service = SQLAlchemyService()
    service._retrieval_semaphore = asyncio.Semaphore(1)

    active_calls = 0
    max_active_calls = 0

    async def on_execute():
        nonlocal active_calls, max_active_calls
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        return _FakeResult([_FakeChunk("chunk-1", "doc-1")])

    service.async_session = lambda: _FakeSession(on_execute)

    await asyncio.gather(
        service.find_similar_chunks("doc-1", [0.1, 0.2], 1),
        service.find_similar_chunks("doc-1", [0.1, 0.2], 1),
    )

    assert max_active_calls <= 1


@pytest.mark.asyncio
async def test_find_similar_chunks_logs_errors():
    service = SQLAlchemyService()

    async def on_execute():
        raise RuntimeError("db error")

    service.async_session = lambda: _FakeSession(on_execute)

    with patch("db.sqlalchemy_service.logger.exception") as mock_log:
        with pytest.raises(RuntimeError, match="db error"):
            await service.find_similar_chunks("doc-1", [0.1, 0.2], 1)

    mock_log.assert_called_once()

import pytest

import db
from db import create_document_with_chunks_atomic
from db.base import ChunkRecord
from services.ingestion_service import ingest_document_atomic

pytestmark = pytest.mark.asyncio


def _make_records(*chunk_texts: str) -> list[ChunkRecord]:
    """Build minimal ChunkRecord objects for testing."""
    records = []
    cursor = 0
    for idx, text in enumerate(chunk_texts):
        records.append(
            ChunkRecord(
                chunk_text=text,
                embedding=[0.1 * (idx + 1), 0.2 * (idx + 1)],
                chunk_index=idx,
                character_offset_start=cursor,
                character_offset_end=cursor + len(text),
                page_number=None,
            )
        )
        cursor += len(text)
    return records


async def test_ingest_document_atomic_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="does not match"):
        await ingest_document_atomic(
            file_name="file.pdf",
            chunks=["only one chunk"],
            embeddings=[],
            tenant_id="dev",
        )


async def test_ingest_document_atomic_calls_atomic_db_path(monkeypatch):
    captured = {}

    async def fake_atomic(file_name: str, chunk_records: list[ChunkRecord], tenant_id: str):
        captured["file_name"] = file_name
        captured["payload"] = chunk_records
        captured["tenant_id"] = tenant_id
        return "doc-789", ["chunk-abc"]

    monkeypatch.setattr("services.ingestion_service.db.create_document_with_chunks_atomic", fake_atomic)

    doc_id, chunk_ids = await ingest_document_atomic(
        file_name="notes.txt",
        chunks=["alpha"],
        embeddings=[[0.5, 0.6]],
        tenant_id="dev",
    )

    assert doc_id == "doc-789"
    assert chunk_ids == ["chunk-abc"]
    assert captured["tenant_id"] == "dev"
    assert captured["file_name"] == "notes.txt"
    records = captured["payload"]
    assert len(records) == 1
    assert isinstance(records[0], ChunkRecord)
    assert records[0].chunk_text == "alpha"
    assert records[0].embedding == [0.5, 0.6]
    assert records[0].chunk_index == 0
    assert records[0].character_offset_start == 0
    assert records[0].character_offset_end == len("alpha")

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


async def test_create_document_with_chunks_atomic_supabase_success(monkeypatch):
    db.db_service = None
    monkeypatch.setattr("core.config.config.APP_ENV", "production")

    async def fake_create_document(self, file_name: str):
        assert file_name == "example.pdf"
        return "doc-123"

    async def fake_store_chunks(self, doc_id: str, chunk_records: list[ChunkRecord]):
        assert doc_id == "doc-123"
        assert len(chunk_records) == 2
        return ["chunk-1", "chunk-2"]

    status_updates = []

    async def fake_update_status(self, doc_id: str, **kwargs):
        status_updates.append((doc_id, kwargs))

    async def fake_cleanup(self, doc_id: str):
        raise AssertionError("cleanup should not be called on success")

    monkeypatch.setattr("db.supabase_service.SupabaseService.create_document", fake_create_document)
    monkeypatch.setattr("db.supabase_service.SupabaseService.store_chunks_with_embeddings", fake_store_chunks)
    monkeypatch.setattr("db.supabase_service.SupabaseService.update_document_status", fake_update_status)
    monkeypatch.setattr("db.supabase_service.SupabaseService.delete_document_chunks", fake_cleanup)

    doc_id, chunk_ids = await create_document_with_chunks_atomic(
        file_name="example.pdf",
        chunk_records=_make_records("chunk a", "chunk b"),
    )

    assert doc_id == "doc-123"
    assert chunk_ids == ["chunk-1", "chunk-2"]
    assert status_updates[0][0] == "doc-123"
    assert status_updates[0][1]["status"] == "completed"


async def test_create_document_with_chunks_atomic_supabase_failure_cleanup(monkeypatch):
    db.db_service = None
    monkeypatch.setattr("core.config.config.APP_ENV", "production")

    async def fake_create_document(self, file_name: str):
        return "doc-rollback"

    async def fake_store_chunks(self, doc_id: str, chunk_records: list[ChunkRecord]):
        raise RuntimeError("chunk insert failed")

    cleanup_calls = []
    status_updates = []

    async def fake_cleanup(self, doc_id: str):
        cleanup_calls.append(doc_id)

    async def fake_update_status(self, doc_id: str, **kwargs):
        status_updates.append((doc_id, kwargs))

    monkeypatch.setattr("db.supabase_service.SupabaseService.create_document", fake_create_document)
    monkeypatch.setattr("db.supabase_service.SupabaseService.store_chunks_with_embeddings", fake_store_chunks)
    monkeypatch.setattr("db.supabase_service.SupabaseService.delete_document_chunks", fake_cleanup)
    monkeypatch.setattr("db.supabase_service.SupabaseService.update_document_status", fake_update_status)

    with pytest.raises(RuntimeError, match="chunk insert failed"):
        await create_document_with_chunks_atomic(
            file_name="broken.pdf",
            chunk_records=_make_records("chunk"),
        )

    assert cleanup_calls == ["doc-rollback"]
    assert status_updates[0][0] == "doc-rollback"
    assert status_updates[0][1]["status"] == "failed"
    update_call_args = status_updates[0][1]
    assert update_call_args["error"]["message"] == "Document processing failed."
    assert "chunk insert failed" not in str(update_call_args)


async def test_ingest_document_atomic_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="does not match"):
        await ingest_document_atomic(
            file_name="file.pdf",
            chunks=["only one chunk"],
            embeddings=[],
        )


async def test_ingest_document_atomic_calls_atomic_db_path(monkeypatch):
    captured = {}

    async def fake_atomic(file_name: str, chunk_records: list[ChunkRecord]):
        captured["file_name"] = file_name
        captured["payload"] = chunk_records
        return "doc-789", ["chunk-abc"]

    monkeypatch.setattr("services.ingestion_service.db.create_document_with_chunks_atomic", fake_atomic)

    doc_id, chunk_ids = await ingest_document_atomic(
        file_name="notes.txt",
        chunks=["alpha"],
        embeddings=[[0.5, 0.6]],
    )

    assert doc_id == "doc-789"
    assert chunk_ids == ["chunk-abc"]
    assert captured["file_name"] == "notes.txt"
    records = captured["payload"]
    assert len(records) == 1
    assert isinstance(records[0], ChunkRecord)
    assert records[0].chunk_text == "alpha"
    assert records[0].embedding == [0.5, 0.6]
    assert records[0].chunk_index == 0
    assert records[0].character_offset_start == 0
    assert records[0].character_offset_end == len("alpha")

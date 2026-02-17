import pytest
from db import create_document_with_chunks_atomic
from services.ingestion_service import ingest_document_atomic

pytestmark = pytest.mark.asyncio

async def test_create_document_with_chunks_atomic_supabase_success(monkeypatch):
    # Mock the service selection
    monkeypatch.setattr("core.config.config.APP_ENV", "production")
    
    # Mock the SupabaseService methods
    async def fake_create_document(self, file_name: str):
        assert file_name == "example.pdf"
        return "doc-123"

    async def fake_store_chunks(self, doc_id: str, chunks_with_embeddings):
        assert doc_id == "doc-123"
        assert len(chunks_with_embeddings) == 2
        return ["chunk-1", "chunk-2"]

    cleanup_calls: list[str] = []

    async def fake_cleanup(self, doc_id: str):
        cleanup_calls.append(doc_id)

    # Apply mocks to the service class - update paths to match your structure
    monkeypatch.setattr("db.supabase_service.SupabaseService.create_document", fake_create_document)
    monkeypatch.setattr("db.supabase_service.SupabaseService.store_chunks_with_embeddings", fake_store_chunks)
    monkeypatch.setattr("db.supabase_service.SupabaseService._cleanup_orphaned_document", fake_cleanup)

    doc_id, chunk_ids = await create_document_with_chunks_atomic(
        file_name="example.pdf",
        chunks_with_embeddings=[
            ("chunk a", [0.1, 0.2]),
            ("chunk b", [0.3, 0.4]),
        ],
    )

    assert doc_id == "doc-123"
    assert chunk_ids == ["chunk-1", "chunk-2"]
    assert cleanup_calls == []

async def test_create_document_with_chunks_atomic_supabase_cleanup_on_chunk_failure(monkeypatch):
    monkeypatch.setattr("core.config.config.APP_ENV", "production")

    async def fake_create_document(self, file_name: str):
        return "doc-rollback"

    async def fake_store_chunks(self, doc_id: str, chunks_with_embeddings):
        raise RuntimeError("chunk insert failed")

    cleanup_calls: list[str] = []

    async def fake_cleanup(self, doc_id: str):
        cleanup_calls.append(doc_id)

    # Update paths here too
    monkeypatch.setattr("db.supabase_service.SupabaseService.create_document", fake_create_document)
    monkeypatch.setattr("db.supabase_service.SupabaseService.store_chunks_with_embeddings", fake_store_chunks)
    monkeypatch.setattr("db.supabase_service.SupabaseService._cleanup_orphaned_document", fake_cleanup)

    with pytest.raises(RuntimeError, match="chunk insert failed"):
        await create_document_with_chunks_atomic(
            file_name="broken.pdf",
            chunks_with_embeddings=[("chunk", [0.1, 0.2])],
        )

    assert cleanup_calls == ["doc-rollback"]

async def test_ingest_document_atomic_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="does not match"):
        await ingest_document_atomic(
            file_name="file.pdf",
            chunks=["only one chunk"],
            embeddings=[],
        )

async def test_ingest_document_atomic_calls_atomic_db_path(monkeypatch):
    captured = {}

    async def fake_atomic(file_name: str, chunks_with_embeddings):
        captured["file_name"] = file_name
        captured["payload"] = chunks_with_embeddings
        return "doc-789", ["chunk-abc"]

    # Update this path to match your db/__init__.py export
    monkeypatch.setattr("db.create_document_with_chunks_atomic", fake_atomic)

    doc_id, chunk_ids = await ingest_document_atomic(
        file_name="notes.txt",
        chunks=["alpha"],
        embeddings=[[0.5, 0.6]],
    )

    assert doc_id == "doc-789"
    assert chunk_ids == ["chunk-abc"]
    assert captured["file_name"] == "notes.txt"
    assert captured["payload"] == [("alpha", [0.5, 0.6])]
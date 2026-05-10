import pytest
import uuid

from core.config import get_embedding_dim
from db.base import ChunkRecord
from db.sqlalchemy_service import SQLAlchemyService


@pytest.mark.asyncio
async def test_delete_document_atomicity_integration():
    """
    Integration test to verify that deleting a document also removes its chunks.

    Uses SQLAlchemyService directly so this always exercises the transactional
    delete path against local Postgres in CI (avoids coupling to APP_ENV after
    other tests reload core.config). Supabase deletes are covered by the RPC migration.
    """
    import sys
    if sys.platform == "win32":
        pytest.skip("Psycopg async mode not supported with ProactorEventLoop on Windows")
    pytest.importorskip("pgvector")
    dim = get_embedding_dim()
    filler = [0.1] * dim
    db = SQLAlchemyService()
    file_name = f"test_atomicity_{uuid.uuid4()}.pdf"
    
    # 1. Create a document
    doc_id = await db.create_document(file_name)
    
    # 2. Store some chunks
    chunk_records = [
        ChunkRecord(
            chunk_text=f"Chunk {i}",
            embedding=[0.1] * dim,
            chunk_index=i,
            page_number=1,
            character_offset_start=i * 10,
            character_offset_end=(i + 1) * 10
        )
        for i in range(3)
    ]
    await db.store_chunks_with_embeddings(doc_id, chunk_records)
    
    # 3. Verify chunks exist (using a raw query or checking similarity search)
    # For simplicity, we use find_similar_chunks which we know works.
    matches = await db.find_similar_chunks(doc_id, filler, match_count=10)
    assert len(matches) == 3
    
    # 4. Delete the document
    await db.delete_document(doc_id)
    
    # 5. Verify document is gone
    doc = await db.get_document(doc_id)
    assert doc is None
    
    # 6. Verify chunks are gone (orphans check)
    matches_after = await db.find_similar_chunks(doc_id, filler, match_count=10)
    assert len(matches_after) == 0

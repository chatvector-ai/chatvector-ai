# backend/services/db_service.py
from backend.core.clients import supabase_client
import logging
from backend.services.embedding_service import get_embedding
from backend.services.db_service import insert_chunk

logger = logging.getLogger(__name__)

async def ingest_chunks(chunks, doc_id: str):
    """
    Orchestrates chunk ingestion for a single document.

    - Responsible for embedding generation and per-chunk insertion.
    - Assumes chunks are pre-validated and non-empty.
    - Does not implement transactional guarantees; partial ingestion
      may occur if an error is raised mid-process.
    - Error handling, retries, and rollback strategies should be handled
      at the ingestion workflow or API layer.
    """
    inserted_chunk_ids = []
    try:
        for chunk in chunks:
            embedding = await get_embedding(chunk)
            chunk_id = await insert_chunk(doc_id, chunk, embedding)
            inserted_chunk_ids.append(chunk_id)
        return inserted_chunk_ids
    except Exception:
        logger.error(f"Chunk ingestion failed for document {doc_id}")
        raise



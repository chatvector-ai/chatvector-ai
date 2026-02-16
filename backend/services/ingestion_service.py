import logging
from services.db_service import insert_chunks_batch, create_document_with_chunks_atomic

logger = logging.getLogger(__name__)


async def ingest_chunks(chunks: list[str], embeddings: list[list[float]], doc_id: str):
    """
    Insert document chunks with their embeddings in batch.
    Kept for backwards compatibility with legacy callers.
    """
    try:
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Number of chunks ({len(chunks)}) does not match number of embeddings ({len(embeddings)})"
            )
        chunks_with_embeddings = list(zip(chunks, embeddings))
        inserted_chunk_ids = await insert_chunks_batch(doc_id, chunks_with_embeddings)

        logger.info(f"Successfully ingested {len(inserted_chunk_ids)} chunks for document {doc_id}")
        return inserted_chunk_ids

    except Exception as e:
        logger.error(f"Chunk ingestion failed for document {doc_id}: {e}")
        raise


async def ingest_document_atomic(
    file_name: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> tuple[str, list[str]]:
    """
    Persist document + chunks as one logical operation.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Number of chunks ({len(chunks)}) does not match number of embeddings ({len(embeddings)})"
        )

    if not chunks:
        raise ValueError("No content chunks were generated from the uploaded file.")

    chunks_with_embeddings = list(zip(chunks, embeddings))
    doc_id, inserted_chunk_ids = await create_document_with_chunks_atomic(
        file_name=file_name,
        chunks_with_embeddings=chunks_with_embeddings,
    )

    logger.info(
        f"Successfully atomically ingested {len(inserted_chunk_ids)} chunks for document {doc_id}"
    )
    return doc_id, inserted_chunk_ids

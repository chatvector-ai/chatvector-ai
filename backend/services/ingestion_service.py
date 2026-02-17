import logging
import db


logger = logging.getLogger(__name__)

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
    doc_id, inserted_chunk_ids = await db.create_document_with_chunks_atomic(
        file_name=file_name,
        chunks_with_embeddings=chunks_with_embeddings,
    )

    logger.info(
        f"Successfully atomically ingested {len(inserted_chunk_ids)} chunks for document {doc_id}"
    )
    return doc_id, inserted_chunk_ids

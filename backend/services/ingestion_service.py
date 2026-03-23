import logging
import db
from db.base import ChunkRecord


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

    cursor = 0
    chunk_records: list[ChunkRecord] = []
    for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
        start = cursor
        end = start + len(chunk_text)
        chunk_records.append(
            ChunkRecord(
                chunk_text=chunk_text,
                embedding=embedding,
                chunk_index=idx,
                character_offset_start=start,
                character_offset_end=end,
                page_number=None,
            )
        )
        cursor = end

    doc_id, inserted_chunk_ids = await db.create_document_with_chunks_atomic(
        file_name=file_name,
        chunk_records=chunk_records,
    )

    logger.info(
        f"Successfully atomically ingested {len(inserted_chunk_ids)} chunks for document {doc_id}"
    )
    return doc_id, inserted_chunk_ids

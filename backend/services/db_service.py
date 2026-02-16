from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import List

from core.config import config

logger = logging.getLogger(__name__)

# Only import SQLAlchemy if using development
if config.APP_ENV.lower() == "development":
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.future import select
    from core.models import async_session, Document, DocumentChunk

# Keep supabase client for production / cloud mode
else:
    from core.clients import supabase_client


@dataclass
class ChunkMatch:
    """Normalized chunk object returned in Supabase mode."""

    id: str
    chunk_text: str
    document_id: str | None = None
    embedding: list[float] | None = None
    created_at: str | None = None
    similarity: float | None = None


# db funcs
async def create_document(file_name: str):
    """Insert a new document and return its ID."""
    if config.APP_ENV.lower() == "development":
        async with async_session() as session:
            session: AsyncSession  # type hint for IDE

            doc_id = str(uuid.uuid4())
            new_doc = Document(id=doc_id, file_name=file_name)
            session.add(new_doc)
            await session.commit()
            logger.info(f"[DEV] Created document ID {doc_id} for file {file_name}")
            return doc_id
    else:
        try:
            doc = supabase_client.table("documents").insert({"file_name": file_name}).execute()
            doc_id = doc.data[0]["id"]
            logger.info(f"[SUPABASE] Created document ID {doc_id} for file {file_name}")
            return doc_id
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to create document: {e}")
            raise


async def insert_chunks_batch(
    doc_id: str,
    chunks_with_embeddings: list[tuple[str, list[float]]],
) -> list[str]:
    """
    Insert multiple document chunks in a single DB operation.
    Returns list of chunk IDs.
    """
    if config.APP_ENV.lower() == "development":
        async with async_session() as session:
            chunk_rows = []
            chunk_ids = []

            for chunk_text, embedding in chunks_with_embeddings:
                chunk_id = str(uuid.uuid4())
                chunk_ids.append(chunk_id)
                chunk_rows.append(
                    DocumentChunk(
                        id=chunk_id,
                        document_id=doc_id,
                        chunk_text=chunk_text,
                        embedding=embedding,
                    )
                )

            session.add_all(chunk_rows)
            await session.commit()

            logger.info(f"[DEV] Inserted {len(chunk_ids)} chunks for document {doc_id}")
            return chunk_ids

    else:
        try:
            payload = [
                {
                    "document_id": doc_id,
                    "chunk_text": chunk_text,
                    "embedding": embedding,
                }
                for chunk_text, embedding in chunks_with_embeddings
            ]

            result = supabase_client.table("document_chunks").insert(payload).execute()
            chunk_ids = [row["id"] for row in result.data]

            logger.info(f"[SUPABASE] Inserted {len(chunk_ids)} chunks for document {doc_id}")
            return chunk_ids

        except Exception as e:
            logger.error(f"[SUPABASE] Batch insert failed for document {doc_id}: {e}")
            raise


def _cleanup_orphaned_document(doc_id: str) -> None:
    """
    Best-effort cleanup for non-atomic Supabase writes.
    Deletes chunks first, then document.
    """
    try:
        supabase_client.table("document_chunks").delete().eq("document_id", doc_id).execute()
        supabase_client.table("documents").delete().eq("id", doc_id).execute()
        logger.info(f"[SUPABASE] Cleanup succeeded for failed upload document {doc_id}")
    except Exception as cleanup_error:
        logger.error(f"[SUPABASE] Cleanup failed for orphaned document {doc_id}: {cleanup_error}")


async def create_document_with_chunks_atomic(
    file_name: str,
    chunks_with_embeddings: list[tuple[str, list[float]]],
) -> tuple[str, list[str]]:
    """
    Persist document + chunks as one logical unit.

    Development mode:
    - Uses a single SQLAlchemy transaction (true DB atomicity).

    Supabase mode:
    - Uses compensating cleanup on failure, since multi-step client writes
      are not atomic by default.
    """
    if config.APP_ENV.lower() == "development":
        async with async_session() as session:
            session: AsyncSession
            chunk_ids: list[str] = []
            doc_id = str(uuid.uuid4())

            try:
                async with session.begin():
                    session.add(Document(id=doc_id, file_name=file_name))

                    chunk_rows = []
                    for chunk_text, embedding in chunks_with_embeddings:
                        chunk_id = str(uuid.uuid4())
                        chunk_ids.append(chunk_id)
                        chunk_rows.append(
                            DocumentChunk(
                                id=chunk_id,
                                document_id=doc_id,
                                chunk_text=chunk_text,
                                embedding=embedding,
                            )
                        )

                    session.add_all(chunk_rows)

                logger.info(
                    f"[DEV] Atomic upload persisted document {doc_id} with {len(chunk_ids)} chunks"
                )
                return doc_id, chunk_ids
            except Exception as e:
                logger.error(f"[DEV] Atomic upload failed for file {file_name}: {e}")
                raise

    doc_id: str | None = None
    try:
        doc_id = await create_document(file_name)
        chunk_ids = await insert_chunks_batch(doc_id, chunks_with_embeddings)
        logger.info(
            f"[SUPABASE] Upload persisted document {doc_id} with {len(chunk_ids)} chunks"
        )
        return doc_id, chunk_ids
    except Exception as e:
        logger.error(f"[SUPABASE] Atomic upload failed for file {file_name}: {e}")
        if doc_id is not None:
            _cleanup_orphaned_document(doc_id)
        raise


async def locate_matching_chunks(
    doc_id: str,
    query_embedding: List[float],
    match_count: int = 5,
) -> list:
    """
    Return matching chunks for a given document ID using embeddings.
    Always returns chunk-like objects with a chunk_text attribute.
    """
    chunks: list = []

    if config.APP_ENV.lower() == "development":
        async with async_session() as session:
            result = await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc_id)
                .limit(match_count)
            )
            chunks = result.scalars().all()
            logger.debug(f"[DEV] Vector search returned {len(chunks)} chunks for document {doc_id}")
    else:
        try:
            result = supabase_client.rpc(
                "match_chunks",
                {
                    "query_embedding": query_embedding,
                    "match_count": match_count,
                    "filter_document_id": doc_id,
                },
            ).execute()

            for c in result.data:
                chunks.append(
                    ChunkMatch(
                        id=c["id"],
                        document_id=c.get("document_id", doc_id),
                        chunk_text=c["chunk_text"],
                        embedding=c.get("embedding"),
                        created_at=c.get("created_at"),
                        similarity=c.get("similarity"),
                    )
                )

            logger.debug(f"[SUPABASE] Vector search returned {len(chunks)} chunks for document {doc_id}")

        except Exception as e:
            logger.error(f"[SUPABASE] Failed to retrieve chunks for document {doc_id}: {e}")
            raise

    return chunks

# backend/services/db_service.py
import logging
import json
import uuid
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

async def insert_chunk(doc_id: str, chunk_text: str, embedding: List[float]):
    """
    Insert a single document chunk.
    embedding: list of floats
    """
    if config.APP_ENV.lower() == "development":
        async with async_session() as session:
            session: AsyncSession  # type hint for IDE

            chunk_id = str(uuid.uuid4())
            new_chunk = DocumentChunk(
                id=chunk_id,
                document_id=doc_id,
                chunk_text=chunk_text,
                embedding=embedding
            )
            session.add(new_chunk)
            await session.commit()
            logger.info(f"[DEV] Created chunk ID {chunk_id} for document {doc_id}")
            return chunk_id
    else:
        try:
            result = supabase_client.table("document_chunks").insert({
                "document_id": doc_id,
                "chunk_text": chunk_text,
                "embedding": embedding
            }).execute()
            chunk_id = result.data[0]["id"]
            logger.info(f"[SUPABASE] Created chunk ID {chunk_id} for document {doc_id}")
            return chunk_id
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to create chunk for document {doc_id}: {e}")
            raise


async def locate_matching_chunks(doc_id: str, query_embedding: List[float], match_count: int = 5):
    """
    Return matching chunks for a given document ID using embeddings.
    """
    if config.APP_ENV.lower() == "development":
        async with async_session() as session:
            # naive vector search using pgvector functions
            # assumes you have embeddings stored as vector column (Postgres pgvector)
            result = await session.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc_id)
                .limit(match_count)
            )
            chunks = result.scalars().all()
            logger.debug(f"[DEV] Vector search returned {len(chunks)} chunks for document {doc_id}")
            return chunks
    else:
        try:
            result = supabase_client.rpc("match_chunks", {
                "query_embedding": query_embedding,
                "match_count": match_count,
                "filter_document_id": doc_id
            }).execute()
            logger.debug(f"[SUPABASE] Vector search returned {len(result.data)} chunks for document {doc_id}")
            return result.data
        except Exception as e:
            logger.error(f"[SUPABASE] Failed to retrieve chunks for document {doc_id}: {e}")
            raise

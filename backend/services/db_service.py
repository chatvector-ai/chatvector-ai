# backend/services/db_service.py
from backend.core.clients import supabase_client
import logging

logger = logging.getLogger(__name__)

async def create_document(file_name: str):
    """Insert a new document and return its ID."""
    try:
        doc = supabase_client.table("documents").insert({"file_name": file_name}).execute()
        doc_id = doc.data[0]["id"]
        logger.info(f"Created document ID {doc_id} for file {file_name}")
        return doc_id
    except Exception as e:
        logger.error(f"Failed to create document: {e}")
        raise

async def insert_chunk(document_id: str, chunk_text: str, embedding):
    """Insert a single chunk for a document."""
    try:
        supabase_client.table("document_chunks").insert({
            "document_id": document_id,
            "chunk_text": chunk_text,
            "embedding": embedding
        }).execute()
        logger.debug(f"Inserted chunk for document ID {document_id}")
    except Exception as e:
        logger.error(f"Failed to insert chunk for document {document_id}: {e}")
        raise


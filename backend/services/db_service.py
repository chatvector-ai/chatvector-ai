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

async def insert_chunk(doc_id: str, chunk_text: str, embedding):
    """
    Inserts a single document chunk into persistent storage.
    -  low-level does not perform embedding generation, batching, retries, or orchestration.
    """
    try:
        result = supabase_client.table("document_chunks").insert({
            "document_id": doc_id,
            "chunk_text": chunk_text,
            "embedding": embedding
        }).execute()

        return result.data[0]["id"]

    except Exception as e:
        logger.error(f"Failed to create chunk for document {doc_id}: {e}")
        raise


async def locate_matching_chunks(doc_id: int, query_embedding, match_count = 5):
    """Insert a new document and return its ID."""
    try:
        result = supabase_client.rpc("match_chunks", {
            "query_embedding": query_embedding,
            "match_count": 5,
            "filter_document_id": doc_id
        }).execute()
        logger.debug(f"Vector search returned {len(result.data)} chunks for document ID {doc_id}")
        return result.data
    except Exception as e:
        logger.error(f"Failed to create document: {e}")
        raise






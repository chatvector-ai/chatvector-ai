import logging
from db.base import ChunkMatch, DatabaseService
from core.clients import supabase_client  

logger = logging.getLogger(__name__)

# Supabase implementation - used in     production
class SupabaseService(DatabaseService):    
    async def create_document(self, filename: str) -> str:
        result = supabase_client.table("documents").insert({
            "file_name": filename,
            "status": "processing"
        }).execute()
        
        doc_id = result.data[0]["id"]
        logger.info(f"[Supabase] Created document {doc_id}")
        return doc_id
    
    async def store_chunks_with_embeddings(
        self, 
        doc_id: str, 
        chunks_with_embeddings: list[tuple[str, list[float]]]
    ) -> list[str]:
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
        
        logger.info(f"[Supabase] Inserted {len(chunk_ids)} chunks for document {doc_id}")
        return chunk_ids
    
    async def get_document(self, doc_id: str) -> dict:
        result = supabase_client.table("documents").select("*").eq("id", doc_id).execute()
        if result.data:
            return result.data[0]
        return None
    
    
    async def create_document_with_chunks_atomic(
        self, 
        file_name: str, 
        chunks_with_embeddings: list[tuple[str, list[float]]]
    ) -> tuple[str, list[str]]:
        """Atomic with compensating cleanup."""
        doc_id = None
        try:
            doc_id = await self.create_document(file_name)
            chunk_ids = await self.store_chunks_with_embeddings(doc_id, chunks_with_embeddings)
            
            logger.info(f"[Supabase] Atomic upload: {doc_id} with {len(chunk_ids)} chunks")
            return doc_id, chunk_ids
            
        except Exception as e:
            logger.error(f"[Supabase] Atomic upload failed: {e}")
            if doc_id:
                await self._cleanup_orphaned_document(doc_id)
            raise

    async def _cleanup_orphaned_document(self, doc_id: str) -> None:
        """Best-effort compensating delete for a document when chunk insert fails."""
        try:
            supabase_client.table("documents").delete().eq("id", doc_id).execute()
            logger.info(f"[Supabase] Cleaned up orphaned document {doc_id}")
        except Exception as cleanup_error:
            logger.error(
                f"[Supabase] Failed to cleanup orphaned document {doc_id}: {cleanup_error}"
            )
    
    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5,
    ) -> list[ChunkMatch]:
        """Find similar chunks using Supabase RPC."""
        try:
            result = supabase_client.rpc(
                "match_chunks",
                {
                    "query_embedding": query_embedding,
                    "match_count": match_count,
                    "filter_document_id": doc_id,
                },
            ).execute()
            
            matches = [
                ChunkMatch(
                    id=c["id"],
                    document_id=c.get("document_id", doc_id),
                    chunk_text=c["chunk_text"],
                    embedding=c.get("embedding"),
                    created_at=c.get("created_at"),
                    similarity=c.get("similarity"),
                )
                for c in result.data
            ]
            
            logger.debug(f"[Supabase] Vector search returned {len(matches)} chunks")
            return matches
            
        except Exception as e:
            logger.error(f"[Supabase] Failed to retrieve chunks: {e}")
            raise
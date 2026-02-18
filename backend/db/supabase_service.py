import logging
from datetime import datetime, timezone

from core.clients import supabase_client
from db.base import ChunkMatch, DatabaseService

logger = logging.getLogger(__name__)


class SupabaseService(DatabaseService):
    """Supabase implementation for production."""

    async def create_document(self, filename: str) -> str:
        result = supabase_client.table("documents").insert(
            {
                "file_name": filename,
                "status": "uploaded",
                "chunks_total": 0,
                "chunks_processed": 0,
            }
        ).execute()

        doc_id = result.data[0]["id"]
        logger.info(f"[Supabase] Created document {doc_id}")
        return doc_id

    async def store_chunks_with_embeddings(
        self,
        doc_id: str,
        chunks_with_embeddings: list[tuple[str, list[float]]],
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

    async def get_document(self, doc_id: str) -> dict | None:
        result = supabase_client.table("documents").select("*").eq("id", doc_id).execute()
        if result.data:
            return result.data[0]
        return None

    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunks_with_embeddings: list[tuple[str, list[float]]],
    ) -> tuple[str, list[str]]:
        """Atomic-like behavior with compensating cleanup for Supabase."""
        doc_id = None
        try:
            doc_id = await self.create_document(file_name)
            chunk_ids = await self.store_chunks_with_embeddings(doc_id, chunks_with_embeddings)
            await self.update_document_status(
                doc_id,
                status="completed",
                chunks_total=len(chunks_with_embeddings),
                chunks_processed=len(chunk_ids),
                failed_stage="",
                error_message="",
            )

            logger.info(f"[Supabase] Atomic upload: {doc_id} with {len(chunk_ids)} chunks")
            return doc_id, chunk_ids

        except Exception as e:
            logger.error(f"[Supabase] Atomic upload failed: {e}")
            if doc_id:
                await self.delete_document_chunks(doc_id)
                await self.update_document_status(
                    doc_id,
                    status="failed",
                    failed_stage="storing",
                    error_message=str(e),
                )
            raise

    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        failed_stage: str | None = None,
        error_message: str | None = None,
        chunks_total: int | None = None,
        chunks_processed: int | None = None,
    ) -> None:
        payload: dict = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if failed_stage is not None:
            payload["failed_stage"] = failed_stage
        if error_message is not None:
            payload["error_message"] = error_message
        if chunks_total is not None:
            payload["chunks_total"] = chunks_total
        if chunks_processed is not None:
            payload["chunks_processed"] = chunks_processed

        supabase_client.table("documents").update(payload).eq("id", doc_id).execute()
        logger.debug(f"[Supabase] Updated status for {doc_id} -> {status}")

    async def get_document_status(self, doc_id: str) -> dict | None:
        result = (
            supabase_client.table("documents")
            .select("id,status,failed_stage,error_message,chunks_total,chunks_processed,created_at,updated_at")
            .eq("id", doc_id)
            .limit(1)
            .execute()
        )

        if not result.data:
            return None

        row = result.data[0]
        return {
            "document_id": row["id"],
            "status": row.get("status"),
            "failed_stage": row.get("failed_stage"),
            "error_message": row.get("error_message"),
            "chunks_total": row.get("chunks_total"),
            "chunks_processed": row.get("chunks_processed"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    async def delete_document_chunks(self, doc_id: str) -> None:
        supabase_client.table("document_chunks").delete().eq("document_id", doc_id).execute()
        logger.info(f"[Supabase] Deleted chunks for failed upload document {doc_id}")

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

import asyncio
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from core.config import config
from core.clients import supabase_client
from db.base import ChunkMatch, ChunkRecord, DatabaseService

logger = logging.getLogger(__name__)


class SupabaseService(DatabaseService):
    """Supabase implementation for production."""

    _executor: ThreadPoolExecutor | None = None
    _executor_workers: int | None = None

    def __init__(self):
        self._io_semaphore = asyncio.Semaphore(config.SUPABASE_IO_CONCURRENCY)

    @classmethod
    def _get_executor(cls) -> ThreadPoolExecutor:
        workers = max(1, int(config.SUPABASE_IO_CONCURRENCY))
        if cls._executor is None or cls._executor_workers != workers:
            if cls._executor is not None:
                cls._executor.shutdown(wait=False, cancel_futures=False)
            cls._executor = ThreadPoolExecutor(
                max_workers=workers,
                thread_name_prefix="supabase-io",
            )
            cls._executor_workers = workers
        return cls._executor

    async def _run_io(self, operation: Callable[[], Any], operation_name: str) -> Any:
        """
        Execute blocking Supabase SDK calls in a thread with bounded concurrency.
        """
        async with self._io_semaphore:
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(self._get_executor(), operation)
            except Exception:
                logger.exception("[Supabase] I/O operation failed: %s", operation_name)
                raise

    async def create_document(self, filename: str) -> str:
        result = await self._run_io(
            lambda: supabase_client.table("documents")
            .insert(
                {
                    "file_name": filename,
                    "status": "uploaded",
                    "chunks": {"total": 0, "processed": 0},
                }
            )
            .execute(),
            operation_name="create_document",
        )

        doc_id = result.data[0]["id"]
        logger.info(f"[Supabase] Created document {doc_id}")
        return doc_id

    async def store_chunks_with_embeddings(
        self,
        doc_id: str,
        chunk_records: list[ChunkRecord],
    ) -> list[str]:
        payload = [
            {
                "document_id": doc_id,
                "chunk_text": record.chunk_text,
                "embedding": record.embedding,
                "chunk_index": record.chunk_index,
                "page_number": record.page_number,
                "character_offset_start": record.character_offset_start,
                "character_offset_end": record.character_offset_end,
            }
            for record in chunk_records
        ]

        result = await self._run_io(
            lambda: supabase_client.table("document_chunks").insert(payload).execute(),
            operation_name="store_chunks_with_embeddings",
        )
        chunk_ids = [row["id"] for row in result.data]

        logger.info(f"[Supabase] Inserted {len(chunk_ids)} chunks for document {doc_id}")
        return chunk_ids

    async def get_document(self, doc_id: str) -> dict | None:
        result = await self._run_io(
            lambda: supabase_client.table("documents").select("*").eq("id", doc_id).execute(),
            operation_name="get_document",
        )
        if result.data:
            return result.data[0]
        return None

    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunk_records: list[ChunkRecord],
    ) -> tuple[str, list[str]]:
        """Atomic-like behavior with compensating cleanup for Supabase."""
        doc_id = None
        try:
            doc_id = await self.create_document(file_name)
            chunk_ids = await self.store_chunks_with_embeddings(doc_id, chunk_records)
            await self.update_document_status(
                doc_id,
                status="completed",
                chunks={"total": len(chunk_records), "processed": len(chunk_ids)},
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
                    error={"stage": "storing", "message": str(e)},
                )
            raise

    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        error: dict | None = None,
        chunks: dict | None = None,
    ) -> None:
        payload: dict = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if error is not None:
            payload["error"] = error
        if chunks is not None:
            payload["chunks"] = chunks

        await self._run_io(
            lambda: supabase_client.table("documents").update(payload).eq("id", doc_id).execute(),
            operation_name="update_document_status",
        )
        logger.debug(f"[Supabase] Updated status for {doc_id} -> {status}")

    async def get_document_status(self, doc_id: str) -> dict | None:
        result = await self._run_io(
            lambda: supabase_client.table("documents")
            .select("id,status,chunks,error,created_at,updated_at")
            .eq("id", doc_id)
            .limit(1)
            .execute(),
            operation_name="get_document_status",
        )

        if not result.data:
            return None

        row = result.data[0]
        return {
            "document_id": row["id"],
            "status": row.get("status"),
            "chunks": row.get("chunks"),
            "error": row.get("error"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    async def delete_document_chunks(self, doc_id: str) -> None:
        await self._run_io(
            lambda: supabase_client.table("document_chunks").delete().eq("document_id", doc_id).execute(),
            operation_name="delete_document_chunks",
        )
        logger.info(f"[Supabase] Deleted chunks for failed upload document {doc_id}")

    async def delete_document(self, document_id: str) -> None:
        # Delete chunks first to respect foreign key constraints
        await self._run_io(
            lambda: supabase_client.table("document_chunks")
            .delete()
            .eq("document_id", document_id)
            .execute(),
            operation_name="delete_document_chunks",
        )
        await self._run_io(
            lambda: supabase_client.table("documents")
            .delete()
            .eq("id", document_id)
            .execute(),
            operation_name="delete_document",
        )
        logger.info(f"[Supabase] Deleted document {document_id} and its chunks")

    async def fail_stale_documents(self, statuses: list[str]) -> int:
        result = await self._run_io(
            lambda: supabase_client.table("documents")
            .update(
                {
                    "status": "failed",
                    "error": {
                        "stage": "server_restart",
                        "message": "Server restarted while document was being processed.",
                    },
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .in_("status", statuses)
            .execute(),
            operation_name="fail_stale_documents",
        )
        count = len(result.data) if result.data else 0
        logger.info(f"[Supabase] Marked {count} stale document(s) as failed on startup")
        return count

    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5,
    ) -> list[ChunkMatch]:
        """Find similar chunks using Supabase RPC."""
        try:
            result = await self._run_io(
                lambda: supabase_client.rpc(
                    "match_chunks",
                    {
                        "query_embedding": query_embedding,
                        "match_count": match_count,
                        "filter_document_id": doc_id,
                    },
                ).execute(),
                operation_name="find_similar_chunks",
            )

            matches = [
                ChunkMatch(
                    id=c["id"],
                    document_id=c.get("document_id", doc_id),
                    chunk_text=c["chunk_text"],
                    embedding=c.get("embedding"),
                    created_at=c.get("created_at"),
                    similarity=c.get("similarity"),
                    chunk_index=c.get("chunk_index"),
                    page_number=c.get("page_number"),
                    character_offset_start=c.get("character_offset_start"),
                    character_offset_end=c.get("character_offset_end"),
                    file_name=c.get("file_name"),
                )
                for c in result.data
            ]

            logger.debug(f"[Supabase] Vector search returned {len(matches)} chunks")
            return matches

        except Exception as e:
            logger.error(f"[Supabase] Failed to retrieve chunks: {e}")
            raise

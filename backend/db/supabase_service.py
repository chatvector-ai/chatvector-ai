import asyncio
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

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

    async def create_document(self, filename: str, tenant_id: Optional[str] = None) -> str:
        payload: dict = {
            "file_name": filename,
            "status": "uploaded",
            "chunks": {"total": 0, "processed": 0},
        }
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id

        result = await self._run_io(
            lambda: supabase_client.table("documents").insert(payload).execute(),
            operation_name="create_document",
        )

        doc_id = result.data[0]["id"]
        logger.info(f"[Supabase] Created document {doc_id} (tenant={tenant_id})")
        return doc_id

    async def store_chunks_with_embeddings(
        self,
        doc_id: str,
        chunk_records: list[ChunkRecord],
        tenant_id: Optional[str] = None,
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

    async def get_document(self, doc_id: str, tenant_id: Optional[str] = None) -> dict | None:
        _tenant = tenant_id

        def _op():
            q = supabase_client.table("documents").select("*").eq("id", doc_id)
            if _tenant is not None:
                q = q.eq("tenant_id", _tenant)
            return q.execute()

        result = await self._run_io(_op, operation_name="get_document")
        if result.data:
            return result.data[0]
        return None

    async def create_document_with_chunks_atomic(
        self,
        file_name: str,
        chunk_records: list[ChunkRecord],
        tenant_id: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Atomic-like behavior with compensating cleanup for Supabase."""
        doc_id = None
        try:
            doc_id = await self.create_document(file_name, tenant_id=tenant_id)
            chunk_ids = await self.store_chunks_with_embeddings(doc_id, chunk_records, tenant_id=tenant_id)
            await self.update_document_status(
                doc_id,
                status="completed",
                chunks={"total": len(chunk_records), "processed": len(chunk_ids)},
                tenant_id=tenant_id,
            )

            logger.info(f"[Supabase] Atomic upload: {doc_id} with {len(chunk_ids)} chunks")
            return doc_id, chunk_ids

        except Exception as e:
            logger.error(f"[Supabase] Atomic upload failed: {e}")
            if doc_id:
                await self.delete_document_chunks(doc_id, tenant_id=tenant_id)
                await self.update_document_status(
                    doc_id,
                    status="failed",
                    error={
                        "stage": "storing", 
                        "code": "pipeline_error", 
                        "message": "Document processing failed."
                    },
                    tenant_id=tenant_id,
                )
            raise

    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        error: dict | None = None,
        chunks: dict | None = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        update_payload: dict = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if error is not None:
            update_payload["error"] = error
        if chunks is not None:
            update_payload["chunks"] = chunks

        _tenant = tenant_id

        def _op():
            q = supabase_client.table("documents").update(update_payload).eq("id", doc_id)
            if _tenant is not None:
                q = q.eq("tenant_id", _tenant)
            return q.execute()

        await self._run_io(_op, operation_name="update_document_status")
        logger.debug(f"[Supabase] Updated status for {doc_id} -> {status}")

    async def get_document_status(self, doc_id: str, tenant_id: Optional[str] = None) -> dict | None:
        _tenant = tenant_id

        def _op():
            q = (
                supabase_client.table("documents")
                .select("id,status,chunks,error,created_at,updated_at")
                .eq("id", doc_id)
            )
            if _tenant is not None:
                q = q.eq("tenant_id", _tenant)
            return q.limit(1).execute()

        result = await self._run_io(_op, operation_name="get_document_status")

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

    async def delete_document_chunks(self, doc_id: str, tenant_id: Optional[str] = None) -> None:
        await self._run_io(
            lambda: supabase_client.table("document_chunks").delete().eq("document_id", doc_id).execute(),
            operation_name="delete_document_chunks",
        )
        logger.info(f"[Supabase] Deleted chunks for failed upload document {doc_id}")

    async def delete_document(self, document_id: str, tenant_id: Optional[str] = None) -> None:
        """Atomically delete a document and its chunks using RPC.

        When tenant_id is provided, ownership is verified before deletion so that
        a tenant cannot delete another tenant's document.
        """
        if tenant_id is not None:
            existing = await self.get_document(document_id, tenant_id=tenant_id)
            if existing is None:
                logger.warning(
                    "[Supabase] delete_document: doc %s not found for tenant %s — skipping",
                    document_id,
                    tenant_id,
                )
                return

        try:
            await self._run_io(
                lambda: supabase_client.rpc(
                    "delete_document_atomic", {"target_document_id": document_id}
                ).execute(),
                operation_name="delete_document_atomic",
            )
            logger.info(f"[Supabase] Atomically deleted document {document_id}")
        except Exception as e:
            logger.error(f"[Supabase] Deletion failed for document {document_id}: {e}")
            raise

    async def fail_stale_documents(self, statuses: list[str], tenant_id: Optional[str] = None) -> set[str]:
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
        doc_ids = {row["id"] for row in result.data} if result.data else set()
        logger.info(f"[Supabase] Marked {len(doc_ids)} stale document(s) as failed on startup")
        return doc_ids

    async def find_similar_chunks(
        self,
        doc_id: str,
        query_embedding: list[float],
        match_count: int = 5,
        session_id: Optional[str] = None,
        query_text: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[ChunkMatch]:
        """Find similar chunks using Supabase RPC.

        Hybrid retrieval (query_text) is not supported on Supabase — only
        vector search is performed.  Tenant isolation is enforced upstream by
        the route-level ownership pre-check; the Supabase `match_chunks` RPC
        filters only by document ID and does not support a tenant_id parameter.
        Cross-tenant access is therefore prevented by the pre-check, not this
        method.  When tenant_id is provided and the doc does not belong to the
        tenant, the pre-check already returned 404 before this is reached.
        """
        del query_text  # hybrid retrieval is SQLAlchemy/PostgreSQL only
        del session_id  # reserved for future session-scoped retrieval
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

    async def list_tenant_documents(self, tenant_id: str) -> list[str]:
        """Return document IDs belonging to tenant_id."""
        _tid = tenant_id

        def _op():
            return (
                supabase_client.table("documents")
                .select("id")
                .eq("tenant_id", _tid)
                .execute()
            )

        result = await self._run_io(_op, operation_name="list_tenant_documents")
        return [row["id"] for row in (result.data or [])]

    async def store_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tenant_id: Optional[str] = None,
    ) -> str:
        from core.clients import supabase_client
        
        payload = {
            "session_id": session_id,
            "role": role,
            "content": content,
        }
        if tenant_id:
            payload["tenant_id"] = tenant_id

        result = await self._run_io(
            lambda: supabase_client.table("chat_messages")
            .insert(payload)
            .execute(),
            operation_name="store_chat_message",
        )

        msg_id = result.data[0]["id"]
        logger.debug(f"[Supabase] Stored chat message {msg_id} for session {session_id}")
        return msg_id

    async def get_session_history(
        self,
        session_id: str,
        limit: int = 20,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        from core.clients import supabase_client
        
        def _op():
            query = supabase_client.table("chat_messages").select("*").eq("session_id", session_id)
            if tenant_id:
                query = query.eq("tenant_id", tenant_id)
            return query.order("created_at", desc=True).limit(limit).execute()

        result = await self._run_io(_op, operation_name="get_session_history")
        
        messages = result.data or []
        # Return ordered ascending (chronological)
        return [
            {
                "id": msg["id"],
                "role": msg["role"],
                "content": msg["content"],
                "created_at": msg.get("created_at"),
            }
            for msg in reversed(messages)
        ]

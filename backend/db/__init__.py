"""
Database Service Factory
========================

Unified DB interface wrapping SQLAlchemyService with retry logic.
SQLAlchemyService is the only supported backend; DATABASE_URL controls
the target PostgreSQL/pgvector instance.
"""

import logging
import threading
from contextlib import asynccontextmanager

from utils.retry import retry_async
from .base import ChunkMatch, ChunkRecord
from .tenant_scope import require_tenant_id

logger = logging.getLogger(__name__)

# Chosen database service singleton (kept public for tests)
db_service = None

_thread_local = threading.local()


def get_db_service():
    """Return the singleton SQLAlchemyService, preferring a thread-local override.

    RQ worker threads install a thread-local override via
    :func:`worker_db_context` so their async engine is bound to the
    worker's own event loop, not the main thread's.
    """
    thread_local_service = getattr(_thread_local, "db_service_override", None)
    if thread_local_service is not None:
        return thread_local_service

    global db_service

    if db_service is not None:
        return db_service

    from .sqlalchemy_service import SQLAlchemyService

    db_service = SQLAlchemyService()
    logger.info("Using SQLAlchemy database service")
    return db_service


@asynccontextmanager
async def worker_db_context():
    """Install a fresh SQLAlchemyService on the current thread for RQ workers.

    A new :class:`SQLAlchemyService` is created so its async engine is
    bound to the worker thread's event loop rather than the main thread's.
    The engine is disposed on exit.
    """
    from .sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()
    _thread_local.db_service_override = service
    try:
        yield service
    finally:
        _thread_local.db_service_override = None
        try:
            await service.engine.dispose()
        except Exception:
            logger.warning("Failed to dispose worker DB engine")


async def create_document(filename: str, tenant_id: str) -> str:
    tenant_id = require_tenant_id(tenant_id, method="create_document")
    service = get_db_service()

    async def _create():
        return await service.create_document(filename, tenant_id=tenant_id)

    return await retry_async(
        _create,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.create_document",
    )


async def store_chunks_with_embeddings(
    doc_id: str,
    chunk_records: list[ChunkRecord],
    tenant_id: str,
) -> list[str]:
    tenant_id = require_tenant_id(tenant_id, method="store_chunks_with_embeddings")
    service = get_db_service()

    async def _store():
        return await service.store_chunks_with_embeddings(
            doc_id, chunk_records, tenant_id=tenant_id
        )

    return await retry_async(
        _store,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.store_chunks_with_embeddings",
    )


async def get_document(doc_id: str, tenant_id: str) -> dict:
    tenant_id = require_tenant_id(tenant_id, method="get_document")
    service = get_db_service()

    async def _get():
        return await service.get_document(doc_id, tenant_id=tenant_id)

    return await retry_async(
        _get,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.get_document",
    )


async def create_document_with_chunks_atomic(
    file_name: str,
    chunk_records: list[ChunkRecord],
    tenant_id: str,
) -> tuple[str, list[str]]:
    tenant_id = require_tenant_id(tenant_id, method="create_document_with_chunks_atomic")
    service = get_db_service()

    async def _atomic():
        return await service.create_document_with_chunks_atomic(
            file_name, chunk_records, tenant_id=tenant_id
        )

    return await retry_async(
        _atomic,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.create_document_with_chunks_atomic",
    )


async def find_similar_chunks(
    doc_id: str,
    query_embedding: list[float],
    match_count: int,
    *,
    tenant_id: str,
    session_id: str | None = None,
    query_text: str | None = None,
) -> list[ChunkMatch]:
    tenant_id = require_tenant_id(tenant_id, method="find_similar_chunks")
    service = get_db_service()

    async def _search():
        return await service.find_similar_chunks(
            doc_id,
            query_embedding,
            match_count,
            tenant_id=tenant_id,
            session_id=session_id,
            query_text=query_text,
        )

    return await retry_async(
        _search,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.find_similar_chunks",
    )


async def update_document_status(
    doc_id: str,
    status: str,
    tenant_id: str,
    *,
    error: dict | None = None,
    chunks: dict | None = None,
) -> None:
    tenant_id = require_tenant_id(tenant_id, method="update_document_status")
    service = get_db_service()

    async def _update():
        await service.update_document_status(
            doc_id=doc_id,
            status=status,
            tenant_id=tenant_id,
            error=error,
            chunks=chunks,
        )

    await retry_async(
        _update,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.update_document_status",
    )


async def get_document_status(doc_id: str, tenant_id: str) -> dict | None:
    tenant_id = require_tenant_id(tenant_id, method="get_document_status")
    service = get_db_service()

    async def _get_status():
        return await service.get_document_status(doc_id, tenant_id=tenant_id)

    return await retry_async(
        _get_status,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.get_document_status",
    )


async def delete_document_chunks(doc_id: str, tenant_id: str) -> None:
    tenant_id = require_tenant_id(tenant_id, method="delete_document_chunks")
    service = get_db_service()

    async def _cleanup():
        await service.delete_document_chunks(doc_id, tenant_id=tenant_id)

    await retry_async(
        _cleanup,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.delete_document_chunks",
    )


async def delete_document(doc_id: str, tenant_id: str) -> None:
    tenant_id = require_tenant_id(tenant_id, method="delete_document")
    service = get_db_service()

    async def _delete():
        await service.delete_document(doc_id, tenant_id=tenant_id)

    await retry_async(
        _delete,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.delete_document",
    )


async def list_applied_migrations() -> list[str] | None:
    """Return applied migration filenames, or ``None`` before ledger bootstrap."""

    return await get_db_service().list_applied_migrations()


async def fail_stale_documents_global(statuses: list[str]) -> set[str]:
    """Mark in-progress documents as failed across all tenants (startup maintenance)."""
    service = get_db_service()

    async def _fail_stale():
        return await service.fail_stale_documents_global(statuses)

    return await retry_async(
        _fail_stale,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.fail_stale_documents_global",
    )


async def list_tenant_documents(tenant_id: str) -> list[str]:
    tenant_id = require_tenant_id(tenant_id, method="list_tenant_documents")
    service = get_db_service()

    async def _list():
        return await service.list_tenant_documents(tenant_id)

    return await retry_async(
        _list,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.list_tenant_documents",
    )


async def store_chat_message(
    session_id: str,
    role: str,
    content: str,
    tenant_id: str,
) -> str:
    tenant_id = require_tenant_id(tenant_id, method="store_chat_message")
    if role not in ("user", "assistant", "system"):
        raise ValueError(f"Invalid role: {role}")

    service = get_db_service()
    return await service.store_chat_message(
        session_id=session_id, role=role, content=content, tenant_id=tenant_id
    )


async def get_session_history(
    session_id: str,
    tenant_id: str,
    *,
    limit: int = 20,
) -> list[dict]:
    tenant_id = require_tenant_id(tenant_id, method="get_session_history")
    service = get_db_service()

    async def _get():
        return await service.get_session_history(
            session_id=session_id, tenant_id=tenant_id, limit=limit
        )

    return await retry_async(
        _get,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        timeout=10.0,
        func_name=f"{service.__class__.__name__}.get_session_history",
    )


async def create_session_record(session_id: str, tenant_id) -> "Session":
    from core.session import Session  # noqa: F401 (re-exported)

    service = get_db_service()
    return await service.create_session_record(session_id, tenant_id)


async def get_session_record(session_id: str, tenant_id) -> "Session | None":
    service = get_db_service()
    return await service.get_session_record(session_id, tenant_id)


async def list_session_records(tenant_id) -> list:
    service = get_db_service()
    return await service.list_session_records(tenant_id)


async def delete_session_record(session_id: str, tenant_id) -> bool:
    service = get_db_service()
    return await service.delete_session_record(session_id, tenant_id)


async def add_session_document(session_id: str, document_id: str) -> None:
    service = get_db_service()
    await service.add_session_document(session_id, document_id)


__all__ = [
    "get_db_service",
    "create_document",
    "store_chunks_with_embeddings",
    "get_document",
    "create_document_with_chunks_atomic",
    "find_similar_chunks",
    "list_tenant_documents",
    "update_document_status",
    "get_document_status",
    "delete_document_chunks",
    "delete_document",
    "list_applied_migrations",
    "fail_stale_documents_global",
    "store_chat_message",
    "get_session_history",
    "create_session_record",
    "get_session_record",
    "list_session_records",
    "delete_session_record",
    "add_session_document",
    "ChunkMatch",
    "ChunkRecord",
    "db_service",
]

"""
Database Service Factory
========================

Unified DB interface with environment-based backend selection and retry wrappers.
"""

import logging

from core.config import config
from utils.retry import retry_async
from .base import ChunkMatch

logger = logging.getLogger(__name__)

# Chosen database service singleton (kept public for tests)
db_service = None


def get_db_service():
    """Return singleton DB service based on APP_ENV."""
    global db_service

    if db_service is not None:
        return db_service

    if config.APP_ENV.lower() == "development":
        from .sqlalchemy_service import SQLAlchemyService

        db_service = SQLAlchemyService()
        logger.info("Using SQLAlchemy database service (development)")
    else:
        from .supabase_service import SupabaseService

        db_service = SupabaseService()
        logger.info("Using Supabase database service (production)")

    return db_service


async def create_document(filename: str) -> str:
    service = get_db_service()

    async def _create():
        return await service.create_document(filename)

    return await retry_async(
        _create,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.create_document",
    )


async def store_chunks_with_embeddings(
    doc_id: str,
    chunks_with_embeddings: list[tuple[str, list[float]]],
) -> list[str]:
    service = get_db_service()

    async def _store():
        return await service.store_chunks_with_embeddings(doc_id, chunks_with_embeddings)

    return await retry_async(
        _store,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.store_chunks_with_embeddings",
    )


async def get_document(doc_id: str) -> dict:
    service = get_db_service()

    async def _get():
        return await service.get_document(doc_id)

    return await retry_async(
        _get,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.get_document",
    )


async def create_document_with_chunks_atomic(
    file_name: str,
    chunks_with_embeddings: list[tuple[str, list[float]]],
) -> tuple[str, list[str]]:
    """Atomic document+chunk creation with retry logic."""
    service = get_db_service()

    async def _atomic():
        return await service.create_document_with_chunks_atomic(file_name, chunks_with_embeddings)

    return await retry_async(
        _atomic,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.create_document_with_chunks_atomic",
    )


async def find_similar_chunks(
    doc_id: str,
    query_embedding: list[float],
    match_count: int = 5,
) -> list[ChunkMatch]:
    """Find similar chunks with retry logic."""
    service = get_db_service()

    async def _search():
        return await service.find_similar_chunks(doc_id, query_embedding, match_count)

    return await retry_async(
        _search,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.find_similar_chunks",
    )


async def update_document_status(
    doc_id: str,
    status: str,
    failed_stage: str | None = None,
    error_message: str | None = None,
    chunks_total: int | None = None,
    chunks_processed: int | None = None,
) -> None:
    """Persist status/progress updates with retry logic."""
    service = get_db_service()

    async def _update():
        await service.update_document_status(
            doc_id=doc_id,
            status=status,
            failed_stage=failed_stage,
            error_message=error_message,
            chunks_total=chunks_total,
            chunks_processed=chunks_processed,
        )

    await retry_async(
        _update,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.update_document_status",
    )


async def get_document_status(doc_id: str) -> dict | None:
    """Read status/progress payload for polling clients."""
    service = get_db_service()

    async def _get_status():
        return await service.get_document_status(doc_id)

    return await retry_async(
        _get_status,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.get_document_status",
    )


async def delete_document_chunks(doc_id: str) -> None:
    """Cleanup helper for failed uploads."""
    service = get_db_service()

    async def _cleanup():
        await service.delete_document_chunks(doc_id)

    await retry_async(
        _cleanup,
        max_retries=3,
        base_delay=0.5,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.delete_document_chunks",
    )


__all__ = [
    "get_db_service",
    "create_document",
    "store_chunks_with_embeddings",
    "get_document",
    "create_document_with_chunks_atomic",
    "find_similar_chunks",
    "update_document_status",
    "get_document_status",
    "delete_document_chunks",
    "ChunkMatch",
    "db_service",
]

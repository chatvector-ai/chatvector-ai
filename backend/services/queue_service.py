"""
Ingestion Queue — Factory & Public Singleton
=============================================

Thin facade that selects the concrete queue backend (asyncio or Redis)
based on ``config.QUEUE_BACKEND`` and exposes a module-level singleton
that the rest of the application imports.

The singleton is lazy-initialized on first access so that test fixtures
can monkeypatch QUEUE_BACKEND before the backend is chosen.

All existing ``from services.queue_service import …`` imports remain
stable — this module re-exports the shared types from queue_base.
"""

from __future__ import annotations

from services.queue_base import BaseIngestionQueue, DLQEntry, QueueFull, QueueJob

_ingestion_queue: BaseIngestionQueue | None = None


def _create_queue() -> BaseIngestionQueue:
    from core.config import config

    if config.QUEUE_BACKEND == "redis":
        from services.queue_redis import RedisIngestionQueue
        return RedisIngestionQueue()
    from services.queue_asyncio import AsyncioIngestionQueue
    return AsyncioIngestionQueue()


def _get_ingestion_queue() -> BaseIngestionQueue:
    global _ingestion_queue
    if _ingestion_queue is None:
        _ingestion_queue = _create_queue()
    return _ingestion_queue


def _reset_queue_singleton() -> None:
    """Clear the cached singleton so the next access re-evaluates config."""
    global _ingestion_queue
    _ingestion_queue = None


class _QueueProxy:
    """Backwards-compatible proxy so ``ingestion_queue`` works as before."""

    def __getattr__(self, name):
        return getattr(_get_ingestion_queue(), name)

    async def start(self):
        return await _get_ingestion_queue().start()

    async def stop(self):
        return await _get_ingestion_queue().stop()

    async def enqueue(self, job):
        return await _get_ingestion_queue().enqueue(job)

    def queue_position(self, doc_id):
        return _get_ingestion_queue().queue_position(doc_id)

    def queue_size(self):
        return _get_ingestion_queue().queue_size()

    def dlq_jobs(self):
        return _get_ingestion_queue().dlq_jobs()

    def active_worker_count(self):
        return _get_ingestion_queue().active_worker_count()


ingestion_queue = _QueueProxy()

__all__ = [
    "ingestion_queue",
    "QueueJob",
    "DLQEntry",
    "QueueFull",
    "_reset_queue_singleton",
]

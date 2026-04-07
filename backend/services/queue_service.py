"""
Ingestion Queue — Factory & Public Singleton
=============================================

Thin facade that selects the concrete queue backend (asyncio or Redis)
based on ``config.QUEUE_BACKEND`` and exposes a module-level singleton
that the rest of the application imports.

All existing ``from services.queue_service import …`` imports remain
stable — this module re-exports the shared types from queue_base.
"""

from core.config import config
from services.queue_base import BaseIngestionQueue, DLQEntry, QueueFull, QueueJob


def _create_queue() -> BaseIngestionQueue:
    if config.QUEUE_BACKEND == "redis":
        from services.queue_redis import RedisIngestionQueue
        return RedisIngestionQueue()
    from services.queue_asyncio import AsyncioIngestionQueue
    return AsyncioIngestionQueue()


ingestion_queue: BaseIngestionQueue = _create_queue()

__all__ = ["ingestion_queue", "QueueJob", "DLQEntry", "QueueFull"]

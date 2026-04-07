"""
Ingestion Queue — Abstract Base & Shared Types
================================================

Defines the interface that every queue backend must implement, plus the
data classes and rate limiter shared across backends.

Mirrors the db/base.py pattern: shared types live here so both the asyncio
and Redis backends can import them without circular dependencies.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class QueueFull(Exception):
    """Raised when the queue is at capacity."""
    pass


@dataclass
class QueueJob:
    doc_id: str
    file_name: str
    content_type: str
    file_bytes: bytes
    attempt: int = 0
    enqueued_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class DLQEntry:
    """
    Lightweight dead-letter record kept after a job exhausts all retries.

    File bytes are intentionally omitted to avoid unbounded memory growth
    when large uploads fail repeatedly.
    """
    doc_id: str
    file_name: str
    content_type: str
    attempt: int
    error: str
    failed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class TokenBucketRateLimiter:
    """
    Leaky-token-bucket rate limiter for async contexts.

    Allows at most `rate` acquisitions per second with a burst capacity of
    `capacity`.  All callers share the same lock, so they serialize correctly
    even when multiple workers race to acquire a token simultaneously.
    """

    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._capacity, self._tokens + elapsed * self._rate
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_time = (1.0 - self._tokens) / self._rate

            await asyncio.sleep(wait_time)


class BaseIngestionQueue(ABC):
    """Interface that every queue backend must implement."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def enqueue(self, job: QueueJob) -> int: ...

    @abstractmethod
    def queue_position(self, doc_id: str) -> Optional[int]: ...

    @abstractmethod
    def queue_size(self) -> int: ...

    @abstractmethod
    def dlq_jobs(self) -> list[DLQEntry]: ...

    @abstractmethod
    def active_worker_count(self) -> int: ...

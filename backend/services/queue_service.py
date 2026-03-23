"""
Background Ingestion Queue Service
====================================

Decouples file uploads from the embedding pipeline using an in-memory asyncio
queue with a bounded worker pool.  Upload requests return immediately; workers
drain the queue in the background at a controlled rate.

Architecture
------------
- QueueJob         : Immutable job record (doc metadata + raw bytes + attempt counter)
- TokenBucketRateLimiter : Caps concurrent embedding API calls (tokens/sec)
- IngestionQueueService  : asyncio.Queue + worker pool + dead-letter queue (DLQ)

Status flow
-----------
    queued → extracting → chunking → embedding → storing → completed
                                                         ↘ failed (→ DLQ after max retries)

Configuration (via .env / core/config.py)
-----------------------------------------
    QUEUE_WORKER_COUNT     default 3   (1-5 concurrent workers)
    QUEUE_MAX_SIZE         default 100 (hard cap on pending jobs)
    QUEUE_EMBEDDING_RPS    default 2.0 (max embedding API calls/sec)
    QUEUE_JOB_MAX_RETRIES  default 3   (retries before DLQ)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import db
from core.config import config

logger = logging.getLogger(__name__)


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

                # No token available — compute how long to wait outside the lock
                wait_time = (1.0 - self._tokens) / self._rate

            # Release lock before sleeping so other coroutines can proceed
            await asyncio.sleep(wait_time)


class IngestionQueueService:
    """
    Manages a bounded asyncio queue + a pool of background worker tasks.

    Workers pick jobs off the queue, apply rate-limiting before the embedding
    step, and delegate to IngestionPipeline.process_document_background().
    Transient failures are retried (up to QUEUE_JOB_MAX_RETRIES); exhausted
    jobs are appended to the dead-letter queue for operator inspection.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[QueueJob] = asyncio.Queue(
            maxsize=config.QUEUE_MAX_SIZE
        )
        self._dlq: list[DLQEntry] = []
        self._workers: list[asyncio.Task] = []
        self._rate_limiter = TokenBucketRateLimiter(
            rate=config.QUEUE_EMBEDDING_RPS,
            capacity=config.QUEUE_EMBEDDING_RPS,
        )
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn the worker pool.  Safe to call multiple times."""
        if self._running:
            return
        self._running = True
        for i in range(config.QUEUE_WORKER_COUNT):
            self._spawn_worker(worker_id=i)
        logger.info(
            f"Ingestion queue started with {config.QUEUE_WORKER_COUNT} workers "
            f"(max_size={config.QUEUE_MAX_SIZE}, "
            f"embedding_rps={config.QUEUE_EMBEDDING_RPS}, "
            f"max_retries={config.QUEUE_JOB_MAX_RETRIES})"
        )

    def _spawn_worker(self, worker_id: int) -> None:
        """Create a worker task and attach a crash-recovery callback."""
        task = asyncio.create_task(
            self._worker(worker_id=worker_id),
            name=f"ingestion-worker-{worker_id}",
        )
        task.add_done_callback(
            lambda t: self._on_worker_done(t, worker_id=worker_id)
        )
        self._workers.append(task)

    def _on_worker_done(self, task: asyncio.Task, worker_id: int) -> None:
        """Respawn a replacement worker if one exits unexpectedly."""
        try:
            self._workers.remove(task)
        except ValueError:
            pass  # already cleared by stop()

        if task.cancelled() or not self._running:
            return

        exc = task.exception()
        if exc is not None:
            logger.error(
                f"Worker-{worker_id} crashed unexpectedly — respawning: {exc}",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            self._spawn_worker(worker_id=worker_id)

    async def stop(self) -> None:
        """Cancel all workers and wait for them to finish cleanly."""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info(
            f"Ingestion queue stopped (DLQ size={len(self._dlq)})"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, job: QueueJob) -> int:
        """
        Add a job to the queue.

        Returns the 1-indexed queue position of the new job.
        Raises asyncio.QueueFull if the queue is at capacity.
        """
        self._queue.put_nowait(job)
        position = self._queue.qsize()
        logger.info(
            f"Enqueued document {job.doc_id} "
            f"(file={job.file_name!r}, position={position})"
        )
        return position

    def queue_position(self, doc_id: str) -> Optional[int]:
        """
        Return the 1-indexed queue position for *doc_id*, or None if the job
        is not currently waiting in the queue (already processing or done).
        """
        # asyncio.Queue exposes its internal deque as ._queue; safe to read
        # from a single-threaded event loop without additional locking.
        for i, job in enumerate(self._queue._queue):  # type: ignore[attr-defined]
            if job.doc_id == doc_id:
                return i + 1
        return None

    def queue_size(self) -> int:
        return self._queue.qsize()

    def dlq_jobs(self) -> list[DLQEntry]:
        """Read-only view of dead-letter queue entries (file bytes not retained)."""
        return list(self._dlq)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _worker(self, worker_id: int) -> None:
        logger.info(f"Ingestion worker-{worker_id} ready")
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._process_job(job, worker_id)
            except Exception as exc:
                logger.error(
                    f"Worker-{worker_id} unhandled error for "
                    f"document {job.doc_id}: {exc}",
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

        logger.info(f"Ingestion worker-{worker_id} stopped")

    async def _process_job(self, job: QueueJob, worker_id: int) -> None:
        # Lazy import avoids a circular-import at module level
        from services.ingestion_pipeline import IngestionPipeline

        logger.info(
            f"Worker-{worker_id} processing document {job.doc_id} "
            f"(attempt {job.attempt + 1}/{config.QUEUE_JOB_MAX_RETRIES + 1})"
        )

        pipeline = IngestionPipeline()
        try:
            await pipeline.process_document_background(
                doc_id=job.doc_id,
                file_name=job.file_name,
                content_type=job.content_type,
                file_bytes=job.file_bytes,
                rate_limiter=self._rate_limiter,
            )
        except Exception as exc:
            if job.attempt < config.QUEUE_JOB_MAX_RETRIES:
                job.attempt += 1
                logger.warning(
                    f"Document {job.doc_id} failed on attempt {job.attempt} "
                    f"— requeueing: {exc}"
                )
                # Override the "failed" status set by _handle_error so clients
                # polling the status endpoint see "retrying" instead of a
                # misleading permanent failure during a transient retry window.
                try:
                    await db.update_document_status(
                        doc_id=job.doc_id, status="retrying"
                    )
                except Exception as status_err:
                    logger.error(
                        f"Failed to set retrying status for {job.doc_id}: {status_err}"
                    )
                await self._queue.put(job)
            else:
                logger.error(
                    f"Document {job.doc_id} ({job.file_name!r}) exhausted "
                    f"{config.QUEUE_JOB_MAX_RETRIES} retries "
                    f"(final attempt={job.attempt}) — moving to DLQ: {exc}",
                    exc_info=True,
                )
                self._dlq.append(DLQEntry(
                    doc_id=job.doc_id,
                    file_name=job.file_name,
                    content_type=job.content_type,
                    attempt=job.attempt,
                    error=str(exc),
                ))


# Module-level singleton — imported by routes and main.py
ingestion_queue = IngestionQueueService()

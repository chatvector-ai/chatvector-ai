"""
Asyncio In-Memory Ingestion Queue
===================================

Original queue implementation backed by asyncio.Queue with a bounded worker
pool.  Upload requests return immediately; workers drain the queue in the
background at a controlled rate.

Status flow
-----------
    queued → extracting → chunking → embedding → storing → completed
                                                         ↘ failed (→ DLQ after max retries)
"""

import asyncio
import logging
import random
import collections
from typing import Optional

import db
from core.config import config
from services.queue_base import (
    BaseIngestionQueue,
    DLQEntry,
    QueueFull,
    QueueJob,
    TokenBucketRateLimiter,
)

logger = logging.getLogger(__name__)


class AsyncioIngestionQueue(BaseIngestionQueue):
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
        # Mirror asyncio.Queue FIFO order without touching asyncio.Queue private internals.
        self._pending_doc_ids: collections.deque[str] = collections.deque()
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
            pass

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
        Raises QueueFull if the queue is at capacity.
        """
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            raise QueueFull(
                f"Ingestion queue is at capacity ({config.QUEUE_MAX_SIZE})"
            )
        self._pending_doc_ids.append(job.doc_id)
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
        for i, pending_id in enumerate(self._pending_doc_ids):
            if pending_id == doc_id:
                return i + 1
        return None

    def queue_size(self) -> int:
        return self._queue.qsize()

    def dlq_jobs(self) -> list[DLQEntry]:
        """Read-only view of dead-letter queue entries (file bytes not retained)."""
        return list(self._dlq)

    def active_worker_count(self) -> int:
        """Return the number of worker tasks that are still running."""
        return len([w for w in self._workers if not w.done()])

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

            if self._pending_doc_ids:
                head = self._pending_doc_ids.popleft()
                if head != job.doc_id:
                    logger.error(
                        "Ingestion queue order mismatch (worker %s): "
                        "job doc_id=%s deque_head=%s",
                        worker_id,
                        job.doc_id,
                        head,
                    )
            else:
                logger.error(
                    "Ingestion queue: received job %s but pending_doc_ids empty "
                    "(worker %s)",
                    job.doc_id,
                    worker_id,
                )

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
        from services.ingestion_pipeline import IngestionPipeline, UploadPipelineError

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
            if isinstance(exc, UploadPipelineError) and 400 <= exc.status_code < 500:
                logger.error(
                    f"Document {job.doc_id} ({job.file_name!r}) failed with "
                    f"non-retryable pipeline error (HTTP {exc.status_code}) "
                    f"— moving to DLQ: {exc}",
                    exc_info=True,
                )
                self._dlq.append(DLQEntry(
                    doc_id=job.doc_id,
                    file_name=job.file_name,
                    content_type=job.content_type,
                    attempt=job.attempt,
                    error=str(exc),
                ))
                return

            if job.attempt < config.QUEUE_JOB_MAX_RETRIES:
                job.attempt += 1
                cap = config.QUEUE_RETRY_BASE_DELAY * (2 ** job.attempt)
                delay = random.uniform(0, cap)
                logger.warning(
                    f"Document {job.doc_id} failed on attempt {job.attempt} "
                    f"— requeueing after {delay:.2f}s: {exc}"
                )
                try:
                    await db.update_document_status(
                        doc_id=job.doc_id, status="retrying"
                    )
                except Exception as status_err:
                    logger.error(
                        f"Failed to set retrying status for {job.doc_id}: {status_err}"
                    )
                await asyncio.sleep(delay)
                self._pending_doc_ids.append(job.doc_id)
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

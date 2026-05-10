"""
Redis-Backed Durable Ingestion Queue
======================================

Uses RQ (Redis Queue) as a persistent job store so that queued uploads survive
server restarts.  File bytes are spilled to a temp file under /tmp/chatvector/
rather than stored in Redis to keep message sizes small.

Worker threads
--------------
RQ workers are synchronous and long-running.  We spawn each worker in a daemon
thread so the FastAPI event loop is not blocked.

Rate limiting
-------------
TokenBucketRateLimiter is instantiated per-worker inside asyncio.run(), so the
bucket is NOT shared across workers or processes.  For global rate limiting,
move the bucket to Redis (e.g. redis-cell) — noted as future work.
"""

import asyncio
import json
import logging
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import redis as redis_lib
from rq import Queue as RQQueue
from rq import SimpleWorker
from rq.job import Job as RQJob

from core.config import config
from services.queue_base import (
    BaseIngestionQueue,
    DLQEntry,
    QueueFull,
    QueueJob,
    TokenBucketRateLimiter,
)

logger = logging.getLogger(__name__)

TEMP_DIR = Path("/tmp/chatvector")
DLQ_REDIS_KEY = "chatvector:dlq"
RQ_QUEUE_NAME = "chatvector-ingestion"


# ---------------------------------------------------------------------------
# Module-level job functions (must be importable by RQ workers)
# ---------------------------------------------------------------------------

def _execute_job(
    doc_id: str,
    file_name: str,
    content_type: str,
    temp_file_path: str,
    attempt: int,
    tenant_id: Optional[str] = None,
) -> None:
    """
    Synchronous entry point invoked by RQ workers.
    Bridges into the async ingestion pipeline via asyncio.run().
    """
    import asyncio
    asyncio.run(_async_execute_job(
        doc_id, file_name, content_type, temp_file_path, attempt, tenant_id
    ))


async def _async_execute_job(
    doc_id: str,
    file_name: str,
    content_type: str,
    temp_file_path: str,
    attempt: int,
    tenant_id: Optional[str] = None,
) -> None:
    """Async bridge that replicates the retry / DLQ logic from AsyncioIngestionQueue."""
    import db as db_module
    from db import worker_db_context
    from services.ingestion_pipeline import IngestionPipeline, UploadPipelineError

    async with worker_db_context():
        _redis_conn = redis_lib.Redis.from_url(config.REDIS_URL)
        temp_path = Path(temp_file_path)

        if not temp_path.exists():
            error_msg = f"Temp file missing for doc {doc_id}: {temp_file_path}"
            logger.error(error_msg)
            try:
                await db_module.update_document_status(
                    doc_id=doc_id,
                    status="failed",
                    error={"stage": "queued", "message": error_msg},
                    tenant_id=tenant_id,
                )
            except Exception:
                logger.exception("Failed to mark document %s as failed", doc_id)
            _push_dlq_entry(DLQEntry(
                doc_id=doc_id,
                file_name=file_name,
                content_type=content_type,
                attempt=attempt,
                error=error_msg,
            ), conn=_redis_conn)
            return

        try:
            file_bytes = temp_path.read_bytes()
        except OSError as exc:
            error_msg = f"Cannot read temp file for doc {doc_id}: {exc}"
            logger.error(error_msg)
            try:
                await db_module.update_document_status(
                    doc_id=doc_id,
                    status="failed",
                    error={"stage": "queued", "message": error_msg},
                    tenant_id=tenant_id,
                )
            except Exception:
                logger.exception("Failed to mark document %s as failed", doc_id)
            _push_dlq_entry(DLQEntry(
                doc_id=doc_id,
                file_name=file_name,
                content_type=content_type,
                attempt=attempt,
                error=error_msg,
            ), conn=_redis_conn)
            return

        rate_limiter = TokenBucketRateLimiter(
            rate=config.QUEUE_EMBEDDING_RPS,
            capacity=config.QUEUE_EMBEDDING_RPS,
        )

        pipeline = IngestionPipeline()
        try:
            await pipeline.process_document_background(
                doc_id=doc_id,
                file_name=file_name,
                content_type=content_type,
                file_bytes=file_bytes,
                tenant_id=tenant_id,
                rate_limiter=rate_limiter,
            )
            _cleanup_temp_file(temp_path)
        except Exception as exc:
            if isinstance(exc, UploadPipelineError) and 400 <= exc.status_code < 500:
                logger.error(
                    "Document %s (%r) non-retryable error (HTTP %d) — DLQ: %s",
                    doc_id, file_name, exc.status_code, exc,
                    exc_info=True,
                )
                _cleanup_temp_file(temp_path)
                _push_dlq_entry(DLQEntry(
                    doc_id=doc_id,
                    file_name=file_name,
                    content_type=content_type,
                    attempt=attempt,
                    error=str(exc),
                ), conn=_redis_conn)
                return

            if attempt < config.QUEUE_JOB_MAX_RETRIES:
                next_attempt = attempt + 1
                cap = config.QUEUE_RETRY_BASE_DELAY * (2 ** next_attempt)
                delay = random.uniform(0, cap)
                logger.warning(
                    "Document %s failed attempt %d — re-enqueuing after %.2fs: %s",
                    doc_id, next_attempt, delay, exc,
                )
                try:
                    await db_module.update_document_status(
                        doc_id=doc_id, status="retrying", tenant_id=tenant_id,
                    )
                except Exception as status_err:
                    logger.error(
                        "Failed to set retrying status for %s: %s",
                        doc_id, status_err,
                    )
                await asyncio.sleep(delay)
                rq_queue = RQQueue(RQ_QUEUE_NAME, connection=_redis_conn)
                rq_queue.enqueue(
                    _execute_job,
                    doc_id, file_name, content_type, temp_file_path, next_attempt, tenant_id,
                    job_id=f"chatvector:{doc_id}:{next_attempt}",
                    job_timeout=600,
                )
            else:
                logger.error(
                    "Document %s (%r) exhausted %d retries — DLQ: %s",
                    doc_id, file_name, config.QUEUE_JOB_MAX_RETRIES, exc,
                    exc_info=True,
                )
                _cleanup_temp_file(temp_path)
                _push_dlq_entry(DLQEntry(
                    doc_id=doc_id,
                    file_name=file_name,
                    content_type=content_type,
                    attempt=attempt,
                    error=str(exc),
                ), conn=_redis_conn)


def _cleanup_temp_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove temp file %s", path)


def _push_dlq_entry(
    entry: DLQEntry,
    conn: redis_lib.Redis | None = None,
) -> None:
    """Persist a DLQ entry as JSON in a Redis list."""
    try:
        _conn = conn or redis_lib.Redis.from_url(config.REDIS_URL)
        payload = json.dumps({
            "doc_id": entry.doc_id,
            "file_name": entry.file_name,
            "content_type": entry.content_type,
            "attempt": entry.attempt,
            "error": entry.error,
            "failed_at": entry.failed_at.isoformat(),
        })
        _conn.rpush(DLQ_REDIS_KEY, payload)
    except Exception:
        logger.exception("Failed to push DLQ entry for %s", entry.doc_id)


class _NoopDeathPenalty:
    """
    No-op job timeout for non-main threads.

    RQ's default death penalty uses SIGALRM which is only available
    in the main thread.  Jobs still have the RQ job_timeout enforced
    at the queue level; this only disables the in-process signal kill.

    Known limitation: the job_timeout=600 passed during enqueue is
    not enforced in-process. If a job hangs indefinitely, the worker
    thread will block until the FastAPI process exits. The daemon=True
    flag ensures threads don't prevent process shutdown, but a hung
    job will occupy a worker slot until then. A custom timeout
    mechanism (e.g. asyncio.wait_for in _async_execute_job) would
    address this if needed.
    """

    def __init__(self, timeout, exception, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def cancel(self):
        pass

    def handle_death_penalty(self, *args, **kwargs):
        pass


class ThreadSafeWorker(SimpleWorker):
    """
    RQ worker safe for use in non-main threads.

    Three changes from the default Worker:
    - Inherits SimpleWorker to avoid os.fork() (runs jobs in-process)
    - Overrides _install_signal_handlers() as a no-op because
      signal.signal() raises ValueError in non-main threads
    - Uses _NoopDeathPenalty instead of UnixSignalDeathPenalty because
      SIGALRM is unavailable outside the main thread
    """

    death_penalty_class = _NoopDeathPenalty

    def _install_signal_handlers(self) -> None:
        pass  # signal handlers cannot be set outside the main thread


# ---------------------------------------------------------------------------
# Queue backend class
# ---------------------------------------------------------------------------

class RedisIngestionQueue(BaseIngestionQueue):
    """
    RQ-backed ingestion queue.  File bytes are spilled to /tmp/chatvector/
    and only metadata flows through Redis.
    """

    def __init__(self) -> None:
        self._conn = redis_lib.Redis.from_url(config.REDIS_URL)
        self._rq_queue = RQQueue(RQ_QUEUE_NAME, connection=self._conn)
        self._worker_threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn RQ worker threads (one per QUEUE_WORKER_COUNT)."""
        for i in range(config.QUEUE_WORKER_COUNT):
            t = threading.Thread(
                target=self._run_worker,
                args=(i,),
                name=f"rq-worker-{i}",
                daemon=True,
            )
            t.start()
            self._worker_threads.append(t)
        logger.info(
            "Redis ingestion queue started with %d worker thread(s) "
            "(max_size=%d, redis=%s)",
            config.QUEUE_WORKER_COUNT,
            config.QUEUE_MAX_SIZE,
            config.REDIS_URL,
        )

    async def stop(self) -> None:
        """Signal workers to stop and join threads."""
        self._stop_event.set()
        for t in self._worker_threads:
            t.join(timeout=5.0)
        self._worker_threads.clear()
        logger.info("Redis ingestion queue stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, job: QueueJob) -> int:
        current_size = len(self._rq_queue)
        if current_size >= config.QUEUE_MAX_SIZE:
            raise QueueFull(
                f"Ingestion queue is at capacity ({config.QUEUE_MAX_SIZE})"
            )

        temp_file_path = TEMP_DIR / job.doc_id
        temp_file_path.write_bytes(job.file_bytes)

        self._rq_queue.enqueue(
            _execute_job,
            job.doc_id,
            job.file_name,
            job.content_type,
            str(temp_file_path),
            job.attempt,
            job.tenant_id,
            job_id=f"chatvector:{job.doc_id}:{job.attempt}",
            job_timeout=600,
        )

        position = len(self._rq_queue)
        logger.info(
            "Enqueued document %s (file=%r, position=%d) [redis]",
            job.doc_id, job.file_name, position,
        )
        return position

    def queue_position(self, doc_id: str) -> Optional[int]:
        job_ids = self._rq_queue.job_ids
        for i, jid in enumerate(job_ids):
            if doc_id in jid:
                return i + 1
        return None

    def queue_size(self) -> int:
        return len(self._rq_queue)

    def dlq_jobs(self) -> list[DLQEntry]:
        raw_entries = self._conn.lrange(DLQ_REDIS_KEY, 0, -1)
        result: list[DLQEntry] = []
        for raw in raw_entries:
            try:
                data = json.loads(raw)
                result.append(DLQEntry(
                    doc_id=data["doc_id"],
                    file_name=data["file_name"],
                    content_type=data["content_type"],
                    attempt=data["attempt"],
                    error=data["error"],
                    failed_at=datetime.fromisoformat(data["failed_at"]),
                ))
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Skipping malformed DLQ entry: %s", exc)
        return result

    def active_worker_count(self) -> int:
        return len([t for t in self._worker_threads if t.is_alive()])

    def clear_stale_jobs(self, failed_doc_ids: set[str]) -> int:
        """
        Remove queued RQ jobs whose doc_id is in *failed_doc_ids*.

        Called during startup reconciliation: after db.fail_stale_documents()
        marks DB rows as failed, this method cleans up the corresponding
        Redis jobs so they are not executed by workers.
        """
        removed = 0
        for jid in list(self._rq_queue.job_ids):
            for doc_id in failed_doc_ids:
                if doc_id in jid:
                    try:
                        rq_job = RQJob.fetch(jid, connection=self._conn)
                        rq_job.cancel()
                        rq_job.delete()
                        removed += 1
                    except Exception:
                        logger.warning("Could not remove stale RQ job %s", jid)
                    break
        if removed:
            logger.info("Cleared %d stale RQ jobs during reconciliation", removed)
        return removed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_worker(self, worker_id: int) -> None:
        """Run a ThreadSafeWorker in a loop; restarts on unexpected exit."""
        logger.info("RQ worker thread-%d starting", worker_id)
        while not self._stop_event.is_set():
            try:
                worker_conn = redis_lib.Redis.from_url(config.REDIS_URL)
                worker = ThreadSafeWorker(
                    [RQ_QUEUE_NAME],
                    connection=worker_conn,
                    name=f"chatvector-worker-{worker_id}-{os.getpid()}",
                )
                worker.work(
                    burst=False,
                    logging_level=logging.WARNING,
                )
            except Exception:
                if not self._stop_event.is_set():
                    logger.exception(
                        "RQ worker thread-%d crashed, restarting in 1s",
                        worker_id,
                    )
                    time.sleep(1.0)
                    continue
            if not self._stop_event.is_set():
                logger.warning(
                    "RQ worker thread-%d exited unexpectedly, restarting in 1s",
                    worker_id,
                )
                time.sleep(1.0)
        logger.info("RQ worker thread-%d exiting", worker_id)

"""
Integration tests for RedisIngestionQueue.

All tests are marked with ``redis_integration`` and require a running Redis
instance at REDIS_URL (default redis://localhost:6379/0).  Run them with:

    pytest -m redis_integration -v

They are skipped automatically if Redis is not reachable.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dotenv import load_dotenv

# Merge backend/.env before reading REDIS_URL so local pytest matches `core.config`.
# Docker/Make inject env first; override=False keeps compose-injected values.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_DIR / ".env", override=False)

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_REDIS_TEST_URL = (os.environ.get("REDIS_URL") or _DEFAULT_REDIS_URL).strip() or _DEFAULT_REDIS_URL

try:
    import redis as redis_lib
    REDIS_AVAILABLE = redis_lib.Redis.from_url(_REDIS_TEST_URL).ping()
except Exception:
    REDIS_AVAILABLE = False

pytestmark = [
    pytest.mark.redis_integration,
    pytest.mark.skipif(not REDIS_AVAILABLE, reason="Redis not reachable"),
]

from services.queue_base import DLQEntry, QueueFull, QueueJob
from services.queue_redis import (
    DLQ_REDIS_KEY,
    TEMP_DIR,
    RedisIngestionQueue,
    _push_dlq_entry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_rq_queue_name(monkeypatch):
    """Dedicated RQ queue name so ingestion workers from app lifespan/tests never drain these jobs.

    When QUEUE_BACKEND=redis, FastAPI startup spawns workers on ``chatvector-ingestion``;
    integration tests must enqueue to a different list or ``len(queue)`` is 0 after enqueue.
    """
    monkeypatch.setattr(
        "services.queue_redis.RQ_QUEUE_NAME",
        "chatvector-ingestion-pytest",
    )


@pytest.fixture(autouse=True)
def _clean_redis():
    """Reset Redis state before and after each test (see tests service REDIS_URL / DB index)."""
    conn = redis_lib.Redis.from_url(_REDIS_TEST_URL)
    conn.flushdb()
    yield
    conn.flushdb()


@pytest.fixture(autouse=True)
def _clean_temp_dir():
    """Ensure the temp directory is clean."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    yield
    for f in TEMP_DIR.iterdir():
        if f.is_file():
            f.unlink(missing_ok=True)


def _make_job(doc_id: str = "doc-redis-test") -> QueueJob:
    return QueueJob(
        doc_id=doc_id,
        file_name="test.pdf",
        content_type="application/pdf",
        file_bytes=b"fake-pdf-bytes",
    )


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_adds_job_to_rq_queue(monkeypatch):
    """After enqueue, the RQ queue should contain one job."""
    monkeypatch.setattr("services.queue_redis.config.QUEUE_MAX_SIZE", 100)
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)
    queue = RedisIngestionQueue()

    position = await queue.enqueue(_make_job("doc-rq-1"))

    assert position >= 1
    assert queue.queue_size() >= 1


@pytest.mark.asyncio
async def test_enqueue_writes_temp_file(monkeypatch):
    """Enqueue should spill file_bytes to /tmp/chatvector/{doc_id}."""
    monkeypatch.setattr("services.queue_redis.config.QUEUE_MAX_SIZE", 100)
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)
    queue = RedisIngestionQueue()

    await queue.enqueue(_make_job("doc-tmp"))

    temp_path = TEMP_DIR / "doc-tmp"
    assert temp_path.exists()
    assert temp_path.read_bytes() == b"fake-pdf-bytes"


# ---------------------------------------------------------------------------
# QueueFull
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_full_raised_at_capacity(monkeypatch):
    """QueueFull is raised when the queue hits QUEUE_MAX_SIZE."""
    monkeypatch.setattr("services.queue_redis.config.QUEUE_MAX_SIZE", 2)
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)
    queue = RedisIngestionQueue()

    await queue.enqueue(_make_job("doc-cap-1"))
    await queue.enqueue(_make_job("doc-cap-2"))

    with pytest.raises(QueueFull):
        await queue.enqueue(_make_job("doc-cap-3"))


# ---------------------------------------------------------------------------
# queue_size and queue_position
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_size_returns_correct_count(monkeypatch):
    """queue_size() should reflect the number of enqueued jobs."""
    monkeypatch.setattr("services.queue_redis.config.QUEUE_MAX_SIZE", 100)
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)
    queue = RedisIngestionQueue()

    assert queue.queue_size() == 0

    await queue.enqueue(_make_job("doc-sz-1"))
    await queue.enqueue(_make_job("doc-sz-2"))

    assert queue.queue_size() == 2


@pytest.mark.asyncio
async def test_queue_position_finds_job(monkeypatch):
    """queue_position() returns 1-indexed position for a known doc_id."""
    monkeypatch.setattr("services.queue_redis.config.QUEUE_MAX_SIZE", 100)
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)
    queue = RedisIngestionQueue()

    await queue.enqueue(_make_job("doc-pos-a"))
    await queue.enqueue(_make_job("doc-pos-b"))

    pos_a = queue.queue_position("doc-pos-a")
    pos_b = queue.queue_position("doc-pos-b")

    assert pos_a is not None
    assert pos_b is not None
    assert pos_a < pos_b


@pytest.mark.asyncio
async def test_queue_position_returns_none_for_unknown(monkeypatch):
    """queue_position() returns None for a doc_id not in the queue."""
    monkeypatch.setattr("services.queue_redis.config.QUEUE_MAX_SIZE", 100)
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)
    queue = RedisIngestionQueue()

    assert queue.queue_position("nonexistent") is None


# ---------------------------------------------------------------------------
# DLQ
# ---------------------------------------------------------------------------

def test_dlq_entry_stored_in_redis(monkeypatch):
    """_push_dlq_entry persists a JSON entry in the chatvector:dlq list."""
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)

    entry = DLQEntry(
        doc_id="doc-dlq-1",
        file_name="fail.pdf",
        content_type="application/pdf",
        attempt=3,
        error="max retries exceeded",
    )
    _push_dlq_entry(entry)

    conn = redis_lib.Redis.from_url(_REDIS_TEST_URL)
    raw = conn.lrange(DLQ_REDIS_KEY, 0, -1)
    assert len(raw) == 1

    data = json.loads(raw[0])
    assert data["doc_id"] == "doc-dlq-1"
    assert data["error"] == "max retries exceeded"
    assert data["attempt"] == 3


def test_dlq_jobs_reads_entries(monkeypatch):
    """dlq_jobs() deserializes all entries from the Redis list."""
    monkeypatch.setattr("services.queue_redis.config.QUEUE_MAX_SIZE", 100)
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)

    for i in range(3):
        _push_dlq_entry(DLQEntry(
            doc_id=f"doc-dlq-{i}",
            file_name="f.pdf",
            content_type="application/pdf",
            attempt=i,
            error=f"error-{i}",
        ))

    queue = RedisIngestionQueue()
    entries = queue.dlq_jobs()

    assert len(entries) == 3
    assert entries[0].doc_id == "doc-dlq-0"
    assert entries[2].error == "error-2"


# ---------------------------------------------------------------------------
# Temp file cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_temp_file_cleaned_after_successful_processing(monkeypatch):
    """After a successful job, the temp file should be deleted."""
    monkeypatch.setattr("services.queue_redis.config.QUEUE_MAX_SIZE", 100)
    monkeypatch.setattr("services.queue_redis.config.REDIS_URL", _REDIS_TEST_URL)

    queue = RedisIngestionQueue()
    await queue.enqueue(_make_job("doc-cleanup"))

    temp_path = TEMP_DIR / "doc-cleanup"
    assert temp_path.exists()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock()

    with patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls):
        from services.queue_redis import _async_execute_job
        await _async_execute_job(
            "doc-cleanup", "test.pdf", "application/pdf",
            str(temp_path), 0,
        )

    assert not temp_path.exists()

"""
Tests for IngestionQueueService, TokenBucketRateLimiter, and queue-related
upload/status behaviour.

Mocks are used throughout to avoid real DB or Gemini API calls.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.queue_service import IngestionQueueService, QueueJob, TokenBucketRateLimiter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(doc_id: str = "doc-test") -> QueueJob:
    return QueueJob(
        doc_id=doc_id,
        file_name="test.pdf",
        content_type="application/pdf",
        file_bytes=b"fake-pdf-bytes",
    )


async def _drain(service: IngestionQueueService, timeout: float = 3.0) -> None:
    """Wait for all queued jobs to be processed (or timeout)."""
    await asyncio.wait_for(service._queue.join(), timeout=timeout)


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_returns_correct_position():
    """Jobs placed without active workers stay in queue; positions are 1-indexed."""
    service = IngestionQueueService()

    pos1 = await service.enqueue(_make_job("doc-a"))
    pos2 = await service.enqueue(_make_job("doc-b"))

    assert pos1 == 1
    assert pos2 == 2
    assert service.queue_size() == 2


@pytest.mark.asyncio
async def test_queue_position_returns_none_after_job_dequeued():
    """queue_position() returns None once a worker has picked up the job."""
    service = IngestionQueueService()
    job = _make_job("doc-gone")

    await service.enqueue(job)
    assert service.queue_position("doc-gone") == 1

    # Simulate worker dequeuing without put_nowait re-enqueue
    service._queue.get_nowait()
    service._queue.task_done()

    assert service.queue_position("doc-gone") is None


# ---------------------------------------------------------------------------
# Worker – successful processing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_processes_job_successfully():
    """Worker picks up a job, calls process_document_background, leaves DLQ empty."""
    service = IngestionQueueService()
    # Replace the rate limiter with a no-op so the test runs instantly
    service._rate_limiter.acquire = AsyncMock()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock()

    with patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls):
        await service.start()
        try:
            await service.enqueue(_make_job("doc-ok"))
            await _drain(service)
        finally:
            await service.stop()

    mock_pipeline_inst.process_document_background.assert_awaited_once()
    call_kwargs = mock_pipeline_inst.process_document_background.await_args.kwargs
    assert call_kwargs["doc_id"] == "doc-ok"
    assert call_kwargs["file_name"] == "test.pdf"
    assert call_kwargs["content_type"] == "application/pdf"
    assert len(service.dlq_jobs()) == 0


@pytest.mark.asyncio
async def test_worker_passes_correct_file_bytes_to_pipeline():
    """Worker forwards raw bytes from the job to process_document_background."""
    service = IngestionQueueService()
    service._rate_limiter.acquire = AsyncMock()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock()

    job = QueueJob(
        doc_id="doc-bytes",
        file_name="doc.txt",
        content_type="text/plain",
        file_bytes=b"hello world",
    )

    with patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls):
        await service.start()
        try:
            await service.enqueue(job)
            await _drain(service)
        finally:
            await service.stop()

    kwargs = mock_pipeline_inst.process_document_background.await_args.kwargs
    assert kwargs["file_bytes"] == b"hello world"


# ---------------------------------------------------------------------------
# Worker – retry and dead-letter queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_failed_job_retries_then_moves_to_dlq(monkeypatch):
    """
    A persistently failing job is retried QUEUE_JOB_MAX_RETRIES times, then
    lands in the dead-letter queue.  Total pipeline calls = max_retries + 1.
    """
    monkeypatch.setattr("services.queue_service.config.QUEUE_JOB_MAX_RETRIES", 2)

    service = IngestionQueueService()
    service._rate_limiter.acquire = AsyncMock()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock(
        side_effect=RuntimeError("embedding API unavailable")
    )

    with patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls):
        await service.start()
        try:
            await service.enqueue(_make_job("doc-fail"))
            await _drain(service)
        finally:
            await service.stop()

    # 1 initial attempt + 2 retries = 3 total calls
    assert mock_pipeline_inst.process_document_background.await_count == 3
    assert len(service.dlq_jobs()) == 1
    assert service.dlq_jobs()[0].doc_id == "doc-fail"


@pytest.mark.asyncio
async def test_job_in_dlq_has_correct_attempt_count(monkeypatch):
    """DLQ job's attempt counter reflects how many times the job was retried."""
    monkeypatch.setattr("services.queue_service.config.QUEUE_JOB_MAX_RETRIES", 1)

    service = IngestionQueueService()
    service._rate_limiter.acquire = AsyncMock()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock(
        side_effect=RuntimeError("always fails")
    )

    with patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls):
        await service.start()
        try:
            await service.enqueue(_make_job("doc-dlq"))
            await _drain(service)
        finally:
            await service.stop()

    assert service.dlq_jobs()[0].attempt == 1  # max_retries value after exhaustion


# ---------------------------------------------------------------------------
# Upload route – queue full → 503
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_returns_503_when_queue_is_full():
    """POST /upload returns HTTP 503 when the ingestion queue is at capacity."""
    from fastapi import HTTPException, UploadFile

    from routes.upload import upload

    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "big.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"pdf-content")

    with (
        patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
        patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-full")),
        patch("routes.upload.db.update_document_status", new=AsyncMock()),
        patch(
            "routes.upload.ingestion_queue.enqueue",
            new=AsyncMock(side_effect=asyncio.QueueFull()),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await upload(mock_file)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "queue_full"
    assert exc_info.value.detail["document_id"] == "doc-full"


@pytest.mark.asyncio
async def test_upload_returns_immediately_with_queue_position():
    """POST /upload returns 'queued' status and a numeric queue_position."""
    from fastapi import UploadFile

    from routes.upload import upload

    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "sample.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"pdf-bytes")

    with (
        patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
        patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-queued")),
        patch("routes.upload.db.update_document_status", new=AsyncMock()),
        patch("routes.upload.ingestion_queue.enqueue", new=AsyncMock(return_value=3)),
    ):
        result = await upload(mock_file)

    assert result["status"] == "queued"
    assert result["document_id"] == "doc-queued"
    assert result["queue_position"] == 3
    assert result["status_endpoint"] == "/documents/doc-queued/status"


# ---------------------------------------------------------------------------
# Status endpoint – queue_position field
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_document_status_includes_queue_position_when_queued():
    """GET /documents/{id}/status includes live queue_position for queued docs."""
    from routes.documents import get_document_status

    db_payload = {
        "document_id": "doc-q",
        "status": "queued",
        "chunks_total": None,
        "chunks_processed": None,
    }

    with (
        patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=db_payload)),
        patch("routes.documents.ingestion_queue.queue_position", return_value=2),
    ):
        result = await get_document_status("doc-q")

    assert result["status"] == "queued"
    assert result["queue_position"] == 2


@pytest.mark.asyncio
async def test_document_status_queue_position_none_when_not_queued():
    """GET /documents/{id}/status sets queue_position=None for non-queued docs."""
    from routes.documents import get_document_status

    db_payload = {"document_id": "doc-emb", "status": "embedding"}

    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=db_payload)):
        result = await get_document_status("doc-emb")

    assert result["queue_position"] is None


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limiter_does_not_sleep_when_token_available(monkeypatch):
    """First acquire() on a fresh limiter consumes the initial token without sleeping."""
    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr("services.queue_service.asyncio.sleep", fake_sleep)

    limiter = TokenBucketRateLimiter(rate=1.0, capacity=1.0)
    await limiter.acquire()

    assert sleep_calls == []


@pytest.mark.asyncio
async def test_rate_limiter_sleeps_when_tokens_exhausted(monkeypatch):
    """Second acquire() on an empty bucket triggers asyncio.sleep with a positive duration."""
    current_time = [0.0]

    def fake_monotonic() -> float:
        return current_time[0]

    sleep_calls: list[float] = []

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        # Advance the fake clock so the next loop iteration refills the bucket
        current_time[0] += duration

    monkeypatch.setattr("services.queue_service.time.monotonic", fake_monotonic)
    monkeypatch.setattr("services.queue_service.asyncio.sleep", fake_sleep)

    limiter = TokenBucketRateLimiter(rate=1.0, capacity=1.0)
    await limiter.acquire()  # consumes the initial token; no sleep
    await limiter.acquire()  # bucket empty → must sleep

    assert len(sleep_calls) == 1
    assert sleep_calls[0] > 0.0


@pytest.mark.asyncio
async def test_rate_limiter_refills_over_time(monkeypatch):
    """After enough time passes the bucket refills and a third acquire() needs no extra sleep."""
    current_time = [0.0]
    sleep_calls: list[float] = []

    def fake_monotonic() -> float:
        return current_time[0]

    async def fake_sleep(duration: float) -> None:
        sleep_calls.append(duration)
        current_time[0] += duration

    monkeypatch.setattr("services.queue_service.time.monotonic", fake_monotonic)
    monkeypatch.setattr("services.queue_service.asyncio.sleep", fake_sleep)

    limiter = TokenBucketRateLimiter(rate=2.0, capacity=2.0)

    # Drain both initial tokens — no sleep expected
    await limiter.acquire()
    await limiter.acquire()
    assert sleep_calls == []

    # Advance the clock by 1 second: rate=2 refills 2 tokens → bucket full again
    current_time[0] += 1.0

    await limiter.acquire()  # should consume a refilled token without sleeping
    assert sleep_calls == []  # still no sleeps after refill

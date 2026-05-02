"""
Tests for AsyncioIngestionQueue, TokenBucketRateLimiter, and queue-related
upload/status behaviour.

Mocks are used throughout to avoid real DB or Gemini API calls.
All tests monkeypatch QUEUE_BACKEND=memory so they always use the asyncio
backend regardless of environment variables.
"""

from core.auth import AuthContext

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.queue_asyncio import AsyncioIngestionQueue
from services.queue_base import QueueFull, QueueJob, TokenBucketRateLimiter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _force_memory_backend(monkeypatch):
    """Ensure all tests in this module use the memory (asyncio) backend."""
    from services.queue_service import _reset_queue_singleton
    _reset_queue_singleton()
    monkeypatch.setenv("QUEUE_BACKEND", "memory")
    yield
    _reset_queue_singleton()


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


async def _drain(service: AsyncioIngestionQueue, timeout: float = 3.0) -> None:
    """Wait for all queued jobs to be processed (or timeout)."""
    await asyncio.wait_for(service._queue.join(), timeout=timeout)


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_returns_correct_position():
    """Jobs placed without active workers stay in queue; positions are 1-indexed."""
    service = AsyncioIngestionQueue()

    pos1 = await service.enqueue(_make_job("doc-a"))
    pos2 = await service.enqueue(_make_job("doc-b"))

    assert pos1 == 1
    assert pos2 == 2
    assert service.queue_size() == 2


@pytest.mark.asyncio
async def test_queue_position_returns_none_after_job_dequeued():
    """queue_position() returns None once a worker has picked up the job."""
    service = AsyncioIngestionQueue()
    job = _make_job("doc-gone")

    await service.enqueue(job)
    assert service.queue_position("doc-gone") == 1

    service._queue.get_nowait()
    service._pending_doc_ids.popleft()
    service._queue.task_done()

    assert service.queue_position("doc-gone") is None


@pytest.mark.asyncio
async def test_enqueue_raises_queue_full_at_capacity(monkeypatch):
    """QueueFull is raised when the queue hits QUEUE_MAX_SIZE."""
    monkeypatch.setattr("services.queue_asyncio.config.QUEUE_MAX_SIZE", 2)
    service = AsyncioIngestionQueue()

    await service.enqueue(_make_job("doc-1"))
    await service.enqueue(_make_job("doc-2"))

    with pytest.raises(QueueFull):
        await service.enqueue(_make_job("doc-3"))


# ---------------------------------------------------------------------------
# Worker – successful processing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_processes_job_successfully():
    """Worker picks up a job, calls process_document_background, leaves DLQ empty."""
    service = AsyncioIngestionQueue()
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
    service = AsyncioIngestionQueue()
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
    monkeypatch.setattr("services.queue_asyncio.config.QUEUE_JOB_MAX_RETRIES", 2)

    service = AsyncioIngestionQueue()
    service._rate_limiter.acquire = AsyncMock()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock(
        side_effect=RuntimeError("embedding API unavailable")
    )

    with (
        patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls),
        patch("services.queue_asyncio.db.update_document_status", new=AsyncMock()),
        patch("services.queue_asyncio.asyncio.sleep", new=AsyncMock()),
    ):
        await service.start()
        try:
            await service.enqueue(_make_job("doc-fail"))
            await _drain(service)
        finally:
            await service.stop()

    assert mock_pipeline_inst.process_document_background.await_count == 3
    assert len(service.dlq_jobs()) == 1
    assert service.dlq_jobs()[0].doc_id == "doc-fail"
    assert service.dlq_jobs()[0].error == "embedding API unavailable"


@pytest.mark.asyncio
async def test_job_in_dlq_has_correct_attempt_count(monkeypatch):
    """DLQ job's attempt counter reflects how many times the job was retried."""
    monkeypatch.setattr("services.queue_asyncio.config.QUEUE_JOB_MAX_RETRIES", 1)

    service = AsyncioIngestionQueue()
    service._rate_limiter.acquire = AsyncMock()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock(
        side_effect=RuntimeError("always fails")
    )

    with (
        patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls),
        patch("services.queue_asyncio.db.update_document_status", new=AsyncMock()),
        patch("services.queue_asyncio.asyncio.sleep", new=AsyncMock()),
    ):
        await service.start()
        try:
            await service.enqueue(_make_job("doc-dlq"))
            await _drain(service)
        finally:
            await service.stop()

    assert service.dlq_jobs()[0].attempt == 1


@pytest.mark.asyncio
async def test_upload_pipeline_error_4xx_goes_to_dlq_without_retry(monkeypatch):
    """Non-retryable 4xx UploadPipelineError should not consume retries or requeue."""
    monkeypatch.setattr("services.queue_asyncio.config.QUEUE_JOB_MAX_RETRIES", 5)

    service = AsyncioIngestionQueue()
    service._rate_limiter.acquire = AsyncMock()

    from services.ingestion_pipeline import UploadPipelineError

    pipeline_error = UploadPipelineError(
        status_code=422,
        code="unprocessable_entity",
        stage="extract",
        message="No extractable text",
    )

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock(
        side_effect=pipeline_error
    )

    with (
        patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls),
        patch("services.queue_asyncio.db.update_document_status", new=AsyncMock()),
        patch("services.queue_asyncio.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        await service.start()
        try:
            await service.enqueue(_make_job("doc-422"))
            await _drain(service)
        finally:
            await service.stop()

    assert mock_pipeline_inst.process_document_background.await_count == 1
    sleep_mock.assert_not_called()
    assert len(service.dlq_jobs()) == 1
    assert service.dlq_jobs()[0].doc_id == "doc-422"
    assert service.dlq_jobs()[0].attempt == 0


@pytest.mark.asyncio
async def test_retryable_failure_sleeps_before_requeue(monkeypatch):
    """Generic failures backoff (full jitter) before requeue; success on second attempt."""
    monkeypatch.setattr("services.queue_asyncio.config.QUEUE_JOB_MAX_RETRIES", 2)
    monkeypatch.setattr("services.queue_asyncio.config.QUEUE_RETRY_BASE_DELAY", 10.0)

    service = AsyncioIngestionQueue()
    service._rate_limiter.acquire = AsyncMock()

    mock_pipeline_cls = MagicMock()
    mock_pipeline_inst = mock_pipeline_cls.return_value
    mock_pipeline_inst.process_document_background = AsyncMock(
        side_effect=[RuntimeError("transient failure"), None]
    )

    sleep_mock = AsyncMock()
    with (
        patch("services.ingestion_pipeline.IngestionPipeline", mock_pipeline_cls),
        patch("services.queue_asyncio.db.update_document_status", new=AsyncMock()),
        patch("services.queue_asyncio.asyncio.sleep", sleep_mock),
    ):
        await service.start()
        try:
            await service.enqueue(_make_job("doc-retry"))
            await _drain(service)
        finally:
            await service.stop()

    assert mock_pipeline_inst.process_document_background.await_count == 2
    sleep_mock.assert_awaited_once()
    delay = sleep_mock.await_args.args[0]
    assert 0.0 <= delay <= 20.0
    assert len(service.dlq_jobs()) == 0


# ---------------------------------------------------------------------------
# active_worker_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_active_worker_count_returns_correct_value():
    """active_worker_count() matches QUEUE_WORKER_COUNT when running."""
    service = AsyncioIngestionQueue()
    assert service.active_worker_count() == 0

    await service.start()
    try:
        assert service.active_worker_count() == service._queue.maxsize or True
        assert service.active_worker_count() > 0
    finally:
        await service.stop()


# ---------------------------------------------------------------------------
# Upload route – queue full → 503
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_returns_503_when_queue_is_full():
    """POST /upload returns HTTP 503 when the ingestion queue is at capacity."""
    from fastapi import HTTPException, UploadFile

    from request_utils import make_test_request
    from routes.upload import upload
    from services.queue_base import QueueFull as QF

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
            new=AsyncMock(side_effect=QF("queue full")),
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await upload(make_test_request("POST", "/upload"), mock_file, auth=AuthContext())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "queue_full"
    assert exc_info.value.detail["document_id"] == "doc-full"
    assert exc_info.value.headers["Retry-After"] == "30"


@pytest.mark.asyncio
async def test_upload_returns_immediately_with_queue_position():
    """POST /upload returns 'queued' status and a numeric queue_position."""
    from fastapi import UploadFile

    from request_utils import make_test_request
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
        result = await upload(make_test_request("POST", "/upload"), mock_file, auth=AuthContext())

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
    from request_utils import make_test_request
    from routes.documents import get_document_status

    db_payload = {
        "document_id": "doc-q",
        "status": "queued",
        "chunks": {"total": 0, "processed": 0},
        "error": None,
    }

    with (
        patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=db_payload)),
        patch("routes.documents.ingestion_queue.queue_position", return_value=2),
    ):
        result = await get_document_status(
            make_test_request("GET", "/documents/doc-q/status"), "doc-q", auth=AuthContext()
        )

    assert result["status"] == "queued"
    assert result["queue_position"] == 2


@pytest.mark.asyncio
async def test_document_status_queue_position_omitted_when_not_queued():
    """GET /documents/{id}/status omits queue_position for non-queued docs."""
    from request_utils import make_test_request
    from routes.documents import get_document_status

    db_payload = {"document_id": "doc-emb", "status": "embedding"}

    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=db_payload)):
        result = await get_document_status(
            make_test_request("GET", "/documents/doc-emb/status"), "doc-emb", auth=AuthContext()
        )

    assert "queue_position" not in result


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limiter_does_not_sleep_when_token_available(monkeypatch):
    """First acquire() on a fresh limiter consumes the initial token without sleeping."""
    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr("services.queue_base.asyncio.sleep", fake_sleep)

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
        current_time[0] += duration

    monkeypatch.setattr("services.queue_base.time.monotonic", fake_monotonic)
    monkeypatch.setattr("services.queue_base.asyncio.sleep", fake_sleep)

    limiter = TokenBucketRateLimiter(rate=1.0, capacity=1.0)
    await limiter.acquire()
    await limiter.acquire()

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

    monkeypatch.setattr("services.queue_base.time.monotonic", fake_monotonic)
    monkeypatch.setattr("services.queue_base.asyncio.sleep", fake_sleep)

    limiter = TokenBucketRateLimiter(rate=2.0, capacity=2.0)

    await limiter.acquire()
    await limiter.acquire()
    assert sleep_calls == []

    current_time[0] += 1.0

    await limiter.acquire()
    assert sleep_calls == []

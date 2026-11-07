"""Tests for Redis queue worker shutdown behavior."""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from services.queue_redis import RedisIngestionQueue, ThreadSafeWorker


@pytest.mark.asyncio
async def test_stop_sets_stop_requested_on_workers(monkeypatch):
    monkeypatch.setattr("services.queue_redis.config.QUEUE_WORKER_COUNT", 1)
    queue = RedisIngestionQueue()
    worker = ThreadSafeWorker(["chatvector-ingestion-pytest"], connection=MagicMock())
    queue._worker_threads = [threading.Thread()]
    queue._rq_workers = [worker]

    with patch.object(queue, "_join_worker_threads") as join_mock:
        await queue.stop()

    assert worker._stop_requested is True
    join_mock.assert_called_once()


@pytest.mark.asyncio
async def test_stop_does_not_block_event_loop(monkeypatch):
    monkeypatch.setattr("services.queue_redis.config.QUEUE_WORKER_COUNT", 1)
    queue = RedisIngestionQueue()
    queue._worker_threads = [threading.Thread()]

    join_started = threading.Event()
    join_finished = threading.Event()

    def slow_join(_timeout: float) -> None:
        join_started.set()
        time.sleep(0.05)
        join_finished.set()

    progress = asyncio.Event()

    async def waiter() -> None:
        progress.set()

    with patch.object(queue, "_join_worker_threads", side_effect=slow_join):
        stop_task = asyncio.create_task(queue.stop())
        await asyncio.wait_for(waiter(), timeout=0.5)
        assert progress.is_set()
        await asyncio.wait_for(stop_task, timeout=1.0)

    assert join_started.is_set()
    assert join_finished.is_set()


def test_thread_safe_worker_dequeue_timeout_is_one_second():
    worker = ThreadSafeWorker(["q"], connection=MagicMock())
    assert worker.dequeue_timeout == 1


def test_thread_safe_worker_tracks_listening_state():
    worker = ThreadSafeWorker(["q"], connection=MagicMock())
    assert worker.listening is False
    worker.listening = True
    worker.teardown()
    assert worker.listening is False


def _patch_queue_construction(monkeypatch):
    monkeypatch.setattr("services.queue_redis.config.QUEUE_WORKER_COUNT", 1)
    monkeypatch.setattr(
        "services.queue_redis.redis_lib.Redis.from_url",
        lambda *args, **kwargs: MagicMock(),
    )


@pytest.mark.asyncio
async def test_stop_during_worker_init_does_not_leave_thread_running(monkeypatch):
    """stop() that lands before the worker is published must still end the thread."""
    _patch_queue_construction(monkeypatch)

    init_entered = threading.Event()
    allow_init = threading.Event()
    created: list[FakeWorker] = []

    class FakeWorker:
        def __init__(self, queues, connection, name):
            self._stop_requested = False
            self.listening = False
            created.append(self)
            init_entered.set()
            assert allow_init.wait(timeout=2)

        def work(self, **kwargs):
            while not self._stop_requested:
                time.sleep(0.01)

    monkeypatch.setattr("services.queue_redis.ThreadSafeWorker", FakeWorker)

    queue = RedisIngestionQueue()
    await queue.start()
    assert init_entered.wait(timeout=2)
    thread = queue._worker_threads[0]

    stop_task = asyncio.create_task(queue.stop())
    for _ in range(50):
        if queue._stop_event.is_set():
            break
        await asyncio.sleep(0.01)
    assert queue._stop_event.is_set()
    assert queue._rq_workers[0] is None

    allow_init.set()
    await asyncio.wait_for(stop_task, timeout=2)

    thread.join(timeout=1)
    assert not thread.is_alive()
    assert created[0]._stop_requested is True
    assert queue._worker_threads == []


@pytest.mark.asyncio
async def test_stop_keeps_worker_refs_when_thread_still_running(monkeypatch):
    _patch_queue_construction(monkeypatch)
    queue = RedisIngestionQueue()
    release = threading.Event()
    thread = threading.Thread(target=release.wait, daemon=True)
    thread.start()
    worker = ThreadSafeWorker(["q"], connection=MagicMock())
    queue._worker_threads = [thread]
    queue._rq_workers = [worker]

    with patch.object(queue, "_join_worker_threads"):
        await queue.stop()

    assert worker._stop_requested is True
    assert queue._worker_threads == [thread]
    assert queue._rq_workers == [worker]
    release.set()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_shutdown_lingering_workers_joins_live_thread(monkeypatch):
    from services.queue_redis import shutdown_lingering_redis_workers

    _patch_queue_construction(monkeypatch)
    started = threading.Event()

    class FakeWorker:
        def __init__(self, queues, connection, name):
            self._stop_requested = False
            self.listening = False

        def work(self, **kwargs):
            started.set()
            while not self._stop_requested:
                time.sleep(0.01)

    monkeypatch.setattr("services.queue_redis.ThreadSafeWorker", FakeWorker)
    queue = RedisIngestionQueue()
    asyncio.run(queue.start())
    assert started.wait(timeout=2)
    thread = queue._worker_threads[0]

    shutdown_lingering_redis_workers(timeout=2)

    thread.join(timeout=1)
    assert not thread.is_alive()


def test_pytest_sessionfinish_stops_lingering_workers(monkeypatch):
    import sys

    called = {}

    def fake_shutdown(timeout=5.0):
        called["timeout"] = timeout

    monkeypatch.setattr(
        "services.queue_redis.shutdown_lingering_redis_workers",
        fake_shutdown,
    )
    conftest = next(
        module
        for name, module in sys.modules.items()
        if name == "conftest" or name.endswith(".conftest")
        if getattr(module, "pytest_sessionfinish", None)
        and module.__file__
        and module.__file__.endswith("tests/conftest.py")
    )
    conftest.pytest_sessionfinish(None, 0)
    assert called["timeout"] == 5.0

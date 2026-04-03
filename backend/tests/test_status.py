"""Tests for /status health checks and payload helpers."""

from unittest.mock import AsyncMock, patch

import pytest
import routes.status as status_module

from routes.status import (
    _embedding_health_check,
    _llm_health_check,
    _overall_status,
    _run_health_check_with_cache,
)


@pytest.fixture(autouse=True)
def clear_health_check_cache():
    status_module._HEALTH_CHECK_CACHE.clear()
    status_module._HEALTH_CHECK_CACHE_LOCKS.clear()
    yield
    status_module._HEALTH_CHECK_CACHE.clear()
    status_module._HEALTH_CHECK_CACHE_LOCKS.clear()


class _FakeClock:
    def __init__(self, *, monotonic: float = 1000.0, wall: float = 1704067200.0):
        self.monotonic_value = monotonic
        self.wall_value = wall

    def advance(self, seconds: float) -> None:
        self.monotonic_value += seconds
        self.wall_value += seconds

    def monotonic(self) -> float:
        return self.monotonic_value

    def time(self) -> float:
        return self.wall_value


@pytest.mark.asyncio
async def test_embedding_health_check_ok_when_embedding_succeeds():
    with patch(
        "services.embedding_service.get_embedding",
        new=AsyncMock(return_value=[0.1, 0.2]),
    ):
        result = await _embedding_health_check()

    assert result["status"] == "ok"
    assert isinstance(result["latency_ms"], int)
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_embedding_health_check_error_when_embedding_raises():
    with patch(
        "services.embedding_service.get_embedding",
        new=AsyncMock(side_effect=RuntimeError("embedding failed")),
    ):
        result = await _embedding_health_check()

    assert result["status"] == "error"
    assert result["error"] == "embedding failed"


@pytest.mark.asyncio
async def test_llm_health_check_ok_when_generate_answer_succeeds():
    with patch(
        "services.answer_service.generate_answer",
        new=AsyncMock(return_value="All systems nominal."),
    ):
        result = await _llm_health_check()

    assert result["status"] == "ok"
    assert isinstance(result["latency_ms"], int)
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_llm_health_check_error_when_generate_answer_raises():
    with patch(
        "services.answer_service.generate_answer",
        new=AsyncMock(side_effect=RuntimeError("LLM unavailable")),
    ):
        result = await _llm_health_check()

    assert result["status"] == "error"
    assert result["error"] == "error"


@pytest.mark.asyncio
async def test_run_health_check_with_cache_reuses_result_within_ttl(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(status_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(status_module.time, "time", clock.time)
    monkeypatch.setattr(status_module.config, "HEALTH_CHECK_CACHE_TTL_SECONDS", 60)
    health_check = AsyncMock(
        side_effect=[
            {"status": "ok", "latency_ms": 17},
            {"status": "ok", "latency_ms": 99},
        ]
    )

    first = await _run_health_check_with_cache("embedding", health_check)
    clock.advance(30)
    second = await _run_health_check_with_cache("embedding", health_check)

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["latency_ms"] == 17
    assert first["checked_at"] == second["checked_at"]
    assert second["checked_at"].endswith("Z")
    health_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_health_check_with_cache_refreshes_after_ttl(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(status_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(status_module.time, "time", clock.time)
    monkeypatch.setattr(status_module.config, "HEALTH_CHECK_CACHE_TTL_SECONDS", 60)
    health_check = AsyncMock(
        side_effect=[
            {"status": "ok", "latency_ms": 11},
            {"status": "ok", "latency_ms": 29},
        ]
    )

    first = await _run_health_check_with_cache("embedding", health_check)
    clock.advance(61)
    second = await _run_health_check_with_cache("embedding", health_check)

    assert first["cached"] is False
    assert second["cached"] is False
    assert second["latency_ms"] == 29
    assert second["checked_at"] != first["checked_at"]
    assert health_check.await_count == 2


@pytest.mark.asyncio
async def test_run_health_check_with_cache_tracks_embedding_and_llm_independently(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(status_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(status_module.time, "time", clock.time)
    monkeypatch.setattr(status_module.config, "HEALTH_CHECK_CACHE_TTL_SECONDS", 60)
    embedding_check = AsyncMock(
        side_effect=[
            {"status": "ok", "latency_ms": 12},
            {"status": "ok", "latency_ms": 44},
        ]
    )
    llm_check = AsyncMock(return_value={"status": "error", "error": "timeout"})

    first_embedding = await _run_health_check_with_cache("embedding", embedding_check)
    clock.advance(30)
    first_llm = await _run_health_check_with_cache("llm", llm_check)
    clock.advance(40)
    second_embedding = await _run_health_check_with_cache("embedding", embedding_check)
    second_llm = await _run_health_check_with_cache("llm", llm_check)

    assert first_embedding["cached"] is False
    assert first_llm["cached"] is False
    assert second_embedding["cached"] is False
    assert second_embedding["latency_ms"] == 44
    assert second_llm["cached"] is True
    assert second_llm["error"] == "timeout"
    assert embedding_check.await_count == 2
    llm_check.assert_awaited_once()


@pytest.mark.parametrize(
    "db_ok, embedding_ok, llm_ok, expected",
    [
        (True, True, True, "healthy"),
        (True, False, True, "degraded"),
        (True, True, False, "degraded"),
        (True, False, False, "degraded"),
        (False, True, True, "unhealthy"),
        (False, False, False, "unhealthy"),
        (False, True, False, "unhealthy"),
    ],
)
def test_overall_status_combinations(db_ok, embedding_ok, llm_ok, expected):
    assert _overall_status(db_ok, embedding_ok, llm_ok) == expected

"""Tests for /status health checks and payload helpers."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import routes.status as status_module
from fastapi.testclient import TestClient
from routes.status import (
    HEALTH_ERROR_CODES,
    _embedding_health_check,
    _llm_error_code_from_answer_text,
    _llm_health_check,
    _overall_status,
    _redis_health_check,
    _run_health_check_with_cache,
)
from services.answer_service import (
    LLM_MSG_INVALID_API_KEY,
    LLM_MSG_RATE_LIMIT,
    LLM_MSG_TIMEOUT,
)
from services.providers.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)


@pytest.fixture(autouse=True)
def clear_health_check_cache():
    status_module._HEALTH_CHECK_CACHE.clear()
    status_module._HEALTH_CHECK_CACHE_LOCKS.clear()
    with patch("routes.status.redis_client") as mock_redis:
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock(return_value=True)
        yield mock_redis
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


def _assert_stable_error(result: dict) -> None:
    assert result["status"] == "error"
    assert result["error"] in HEALTH_ERROR_CODES


@pytest.mark.asyncio
async def test_embedding_health_check_ok_when_probe_succeeds():
    with patch(
        "services.embedding_service.probe_embedding_health",
        new=AsyncMock(return_value=None),
    ) as mock_probe:
        result = await _embedding_health_check()

    assert result["status"] == "ok"
    assert isinstance(result["latency_ms"], int)
    mock_probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_embedding_health_check_error_uses_stable_code():
    with patch(
        "services.embedding_service.probe_embedding_health",
        new=AsyncMock(side_effect=ProviderRateLimitError("429")),
    ):
        result = await _embedding_health_check()

    _assert_stable_error(result)
    assert result["error"] == "rate_limited"


@pytest.mark.asyncio
async def test_embedding_health_check_maps_rejected_api_key():
    with patch(
        "services.embedding_service.probe_embedding_health",
        new=AsyncMock(side_effect=ProviderAuthError("401 unauthorized")),
    ):
        result = await _embedding_health_check()

    _assert_stable_error(result)
    assert result["error"] == "api_key_invalid"


@pytest.mark.asyncio
async def test_embedding_health_check_timeout_unchanged():
    with patch(
        "services.embedding_service.probe_embedding_health",
        new=AsyncMock(side_effect=ProviderTimeoutError("timed out")),
    ):
        result = await _embedding_health_check()

    _assert_stable_error(result)
    assert result["error"] == "timeout"


@pytest.mark.asyncio
async def test_embedding_health_check_single_attempt_on_rate_limit():
    call_count = 0

    async def _probe(_text: str) -> None:
        nonlocal call_count
        call_count += 1
        raise ProviderRateLimitError("429")

    with patch(
        "services.embedding_service.probe_embedding_health",
        new=AsyncMock(side_effect=_probe),
    ):
        await _embedding_health_check()

    assert call_count == 1


@pytest.mark.asyncio
async def test_llm_health_check_ok_when_probe_returns_tuple():
    with patch(
        "services.answer_service.probe_llm_health",
        new=AsyncMock(return_value=("All systems nominal.", 42, "test-model")),
    ) as mock_probe:
        result = await _llm_health_check()

    assert result["status"] == "ok"
    assert isinstance(result["latency_ms"], int)
    mock_probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_llm_health_check_does_not_use_fallback_on_success_tuple():
    with patch(
        "services.answer_service.probe_llm_health",
        new=AsyncMock(return_value=("healthy", 10, "model")),
    ):
        result = await _llm_health_check()

    assert result["status"] == "ok"
    assert "error" not in result


@pytest.mark.asyncio
async def test_llm_health_check_error_when_probe_raises():
    with patch(
        "services.answer_service.probe_llm_health",
        new=AsyncMock(side_effect=RuntimeError("LLM unavailable")),
    ):
        result = await _llm_health_check()

    _assert_stable_error(result)
    assert result["error"] == "error"


@pytest.mark.asyncio
async def test_llm_health_check_maps_invalid_api_key_answer():
    with patch(
        "services.answer_service.probe_llm_health",
        new=AsyncMock(return_value=(LLM_MSG_INVALID_API_KEY, 0, "")),
    ):
        result = await _llm_health_check()

    _assert_stable_error(result)
    assert result["error"] == "api_key_invalid"


@pytest.mark.asyncio
async def test_llm_health_check_rate_limit_and_timeout_unchanged():
    with patch(
        "services.answer_service.probe_llm_health",
        new=AsyncMock(return_value=(LLM_MSG_RATE_LIMIT, 0, "")),
    ):
        rate_limited = await _llm_health_check()

    with patch(
        "services.answer_service.probe_llm_health",
        new=AsyncMock(return_value=(LLM_MSG_TIMEOUT, 0, "")),
    ):
        timed_out = await _llm_health_check()

    assert rate_limited["error"] == "rate_limited"
    assert timed_out["error"] == "timeout"


def test_llm_error_code_from_answer_text_prefers_invalid_key_over_generic_error():
    assert _llm_error_code_from_answer_text(LLM_MSG_INVALID_API_KEY) == "api_key_invalid"


@pytest.mark.asyncio
async def test_llm_health_check_single_attempt_on_failure():
    call_count = 0

    async def _probe(_q: str, _c: str) -> tuple[str, int, str]:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("fail once")

    with patch(
        "services.answer_service.probe_llm_health",
        new=AsyncMock(side_effect=_probe),
    ):
        await _llm_health_check()

    assert call_count == 1


@pytest.mark.asyncio
async def test_llm_health_check_uses_health_timeout(monkeypatch):
    monkeypatch.setattr(status_module.config, "LLM_HEALTH_CHECK_TIMEOUT_SEC", 7)
    mock_wait_for = AsyncMock(return_value=("ok", 1, "m"))

    with patch("routes.status.asyncio.wait_for", mock_wait_for):
        await _llm_health_check()

    assert mock_wait_for.await_args.kwargs["timeout"] == 7.0


@pytest.mark.asyncio
async def test_redis_health_check_disconnected_uses_stable_code():
    with patch(
        "routes.status.redis_client.ping",
        new=AsyncMock(side_effect=ConnectionError("refused")),
    ):
        result = await _redis_health_check()

    _assert_stable_error(result)
    assert result["error"] == "disconnected"


@pytest.mark.asyncio
async def test_run_health_check_with_cache_reuses_result_within_ttl(monkeypatch, clear_health_check_cache):
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
    health_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_health_check_with_cache_refreshes_after_ttl(monkeypatch, clear_health_check_cache):
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
    assert health_check.await_count == 2


@pytest.mark.parametrize(
    "db_ok, embedding_ok, llm_ok, redis_ok, expected",
    [
        (True, True, True, True, "healthy"),
        (True, False, True, True, "degraded"),
        (True, True, False, True, "degraded"),
        (False, True, True, True, "unhealthy"),
        (True, True, True, False, "unhealthy"),
    ],
)
def test_overall_status_combinations(db_ok, embedding_ok, llm_ok, redis_ok, expected):
    assert _overall_status(db_ok, embedding_ok, llm_ok, redis_ok) == expected


@pytest.mark.asyncio
async def test_run_health_check_with_cache_uses_redis_if_available(monkeypatch, clear_health_check_cache):
    mock_redis = clear_health_check_cache
    clock = _FakeClock()
    monkeypatch.setattr(status_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(status_module.time, "time", clock.time)
    monkeypatch.setattr(status_module.config, "HEALTH_CHECK_CACHE_TTL_SECONDS", 60)
    monkeypatch.setattr(status_module.config, "QUEUE_BACKEND", "redis")

    cached_at = status_module._health_check_checked_at(clock.time())
    mock_redis.get.return_value = json.dumps({
        "result": {"status": "ok", "latency_ms": 5},
        "checked_at": cached_at,
    })

    health_check = AsyncMock(return_value={"status": "ok", "latency_ms": 99})
    result = await _run_health_check_with_cache("embedding", health_check)

    assert result["cached"] is True
    assert result["latency_ms"] == 5
    health_check.assert_not_called()


def test_health_returns_ok():
    import db as db_module
    from main import app
    from services.api_key_service import reset_session_factory

    db_module.db_service = None
    reset_session_factory()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

"""HTTP behavior for the queue stats route (environment gating)."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from core.config import config
from middleware.rate_limit import limiter
from routes.queue import router as queue_router


async def _rate_limit_exceeded_handler(
    _request: Request, _exc: RateLimitExceeded
) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "rate limited"})


def _queue_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(queue_router)
    return app


def test_queue_stats_returns_404_in_production(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    limiter.reset()
    try:
        with TestClient(_queue_app()) as client:
            resp = client.get("/queue/stats")
        assert resp.status_code == 404
    finally:
        limiter.reset()


def test_queue_stats_returns_200_in_non_production(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "development")
    limiter.reset()
    try:
        with TestClient(_queue_app()) as client:
            resp = client.get("/queue/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "queue_size" in data
        assert "dlq" in data
    finally:
        limiter.reset()

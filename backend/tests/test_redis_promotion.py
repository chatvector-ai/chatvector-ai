import os
import importlib
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

def test_queue_backend_default_development():
    """Verify memory queue is default when APP_ENV is development."""
    with patch.dict(os.environ, {"APP_ENV": "development"}, clear=True):
        import core.config
        importlib.reload(core.config)
        config = core.config.Settings()
        assert config.QUEUE_BACKEND == "memory"

def test_queue_backend_default_production():
    """Verify redis queue is default when APP_ENV is production."""
    with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
        import core.config
        importlib.reload(core.config)
        config = core.config.Settings()
        assert config.QUEUE_BACKEND == "redis"

@pytest.mark.asyncio
async def test_startup_validation_redis_unreachable():
    """Verify that lifespan raises an exception and halts startup if Redis is unreachable when configured."""
    from main import lifespan
    from fastapi import FastAPI
    from core.config import config
    import redis as redis_lib

    app = FastAPI()
    
    with patch("main.config.QUEUE_BACKEND", "redis"), \
         patch("core.clients.redis_client.ping", new_callable=AsyncMock) as mock_ping, \
         patch("main.db.fail_stale_documents", new_callable=AsyncMock, return_value=set()), \
         patch("main.ingestion_queue.start", new_callable=AsyncMock), \
         patch("main.ingestion_queue.stop", new_callable=AsyncMock):
        
        mock_ping.side_effect = redis_lib.exceptions.ConnectionError("Connection refused")
        
        with pytest.raises(redis_lib.exceptions.ConnectionError):
            async with lifespan(app):
                pass
                
        mock_ping.assert_called_once()

@pytest.mark.asyncio
async def test_status_endpoint_includes_redis_health():
    """Verify that /status payload includes redis health if QUEUE_BACKEND is redis."""
    from routes.status import _build_payload
    
    with patch("routes.status.config.QUEUE_BACKEND", "redis"):
        payload = _build_payload(
            db_ok=True,
            documents_indexed=10,
            memory_pct=50,
            uptime_str="1h",
            version="1.0.0",
            queue_pending=5,
            workers_active=2,
            embedding_health={"status": "ok", "latency_ms": 10},
            llm_health={"status": "ok", "latency_ms": 100},
            redis_health={"status": "error", "error": "timeout"}
        )
        
        assert payload["components"]["queue"] == "redis (disconnected)"
        assert payload["health_checks"]["redis"]["status"] == "error"
        assert payload["status"] == "unhealthy"
import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import db
from core.auth import AuthContext, require_auth
from core.clients import redis_client
from core.config import config
from middleware.rate_limit import limiter
from routes.root import _is_browser
from services.queue_service import ingestion_queue

logger = logging.getLogger(__name__)

router = APIRouter()

BACKEND_ROOT = Path(__file__).resolve().parent.parent
_BAR_WIDTH = 10
_HEALTH_CHECK_CACHE: dict[str, dict[str, Any]] = {}
_HEALTH_CHECK_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
REDIS_HEALTH_CACHE_PREFIX = "chatvector:health_cache"

HEALTH_ERROR_CODES = frozenset({
    "timeout",
    "rate_limited",
    "api_key_missing",
    "api_key_invalid",
    "disconnected",
    "error",
})


def _read_version() -> str:
    try:
        return (BACKEND_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _process_memory_percent() -> int:
    try:
        return int(round(psutil.Process(os.getpid()).memory_percent()))
    except Exception:
        logger.exception("Failed to read process memory percent")
        return 0


def _format_uptime(start_time: float) -> str:
    elapsed = max(0, int(time.time() - start_time))
    days, rem = divmod(elapsed, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours}h {minutes}m"


def _bar(filled: int, total: int) -> str:
    if total <= 0:
        total = 1
    filled = min(max(filled, 0), total)
    n = int(round((filled / total) * _BAR_WIDTH))
    return "[" + "█" * n + "░" * (_BAR_WIDTH - n) + "]"


def _bar_percent(percent: int) -> str:
    p = min(max(percent, 0), 100)
    n = int(round((p / 100.0) * _BAR_WIDTH))
    return "[" + "█" * n + "░" * (_BAR_WIDTH - n) + "]"


def _workers_active_count() -> int | None:
    try:
        return ingestion_queue.active_worker_count()
    except Exception:
        logger.warning("Worker count unavailable", exc_info=True)
        return None


def _sync_queue_metrics() -> tuple[int, int]:
    return ingestion_queue.queue_size(), ingestion_queue.active_worker_count()


async def _queue_metrics() -> tuple[int | None, int | None]:
    """Return queue depth and active worker count, or (None, None) on failure."""
    try:
        if config.QUEUE_BACKEND == "redis":
            return await asyncio.to_thread(_sync_queue_metrics)
        return ingestion_queue.queue_size(), ingestion_queue.active_worker_count()
    except Exception:
        logger.warning("Queue metrics unavailable", exc_info=True)
        return None, None


async def _database_connected_and_document_count(
    tenant_id: str,
) -> tuple[bool, int | None]:
    service = db.get_db_service()
    return await service.ping_and_count_tenant_documents(tenant_id)


def _classify_provider_exception(exc: BaseException) -> str:
    from services.providers.base import (
        ProviderAuthError,
        ProviderConnectionError,
        ProviderRateLimitError,
        ProviderTimeoutError,
    )

    if isinstance(exc, ProviderRateLimitError):
        return "rate_limited"
    if isinstance(exc, ProviderAuthError):
        return "api_key_invalid"
    if isinstance(exc, (ProviderTimeoutError, ProviderConnectionError, asyncio.TimeoutError)):
        return "timeout"
    return "error"


def _classify_redis_exception(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    try:
        import redis as redis_lib

        if isinstance(exc, (redis_lib.exceptions.ConnectionError, ConnectionError, OSError)):
            return "disconnected"
    except ImportError:
        if isinstance(exc, (ConnectionError, OSError)):
            return "disconnected"
    return "error"


def _health_check_checked_at(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _health_check_response(
    result: dict[str, Any],
    *,
    cached: bool,
    checked_at: str,
) -> dict[str, Any]:
    response = dict(result)
    response["cached"] = cached
    response["checked_at"] = checked_at
    return response


def _health_check_cache_is_fresh(entry: dict[str, Any], now_monotonic: float) -> bool:
    checked_monotonic = entry.get("checked_monotonic")
    if not isinstance(checked_monotonic, (int, float)):
        return False
    return now_monotonic - float(checked_monotonic) < config.HEALTH_CHECK_CACHE_TTL_SECONDS


async def _health_check_cache_hit(check_name: str, now_monotonic: float) -> dict[str, Any] | None:
    # 1. Try Redis first (only if Redis queue is enabled)
    if config.QUEUE_BACKEND == "redis":
        try:
            redis_key = f"{REDIS_HEALTH_CACHE_PREFIX}:{check_name}"
            cached_data = await redis_client.get(redis_key)
            if cached_data:
                entry = json.loads(cached_data)
                cached_result = entry.get("result")
                checked_at = entry.get("checked_at")
                if isinstance(cached_result, dict) and isinstance(checked_at, str):
                    return _health_check_response(cached_result, cached=True, checked_at=checked_at)
        except Exception:
            logger.debug("Redis health cache hit failed, falling back to memory", exc_info=True)

    # 2. Fallback to in-memory cache
    entry = _HEALTH_CHECK_CACHE.get(check_name)
    if not entry or not _health_check_cache_is_fresh(entry, now_monotonic):
        return None

    cached_result = entry.get("result")
    checked_at = entry.get("checked_at")
    if not isinstance(cached_result, dict) or not isinstance(checked_at, str):
        return None

    return _health_check_response(cached_result, cached=True, checked_at=checked_at)


def _health_check_lock(check_name: str) -> asyncio.Lock:
    lock = _HEALTH_CHECK_CACHE_LOCKS.get(check_name)
    if lock is None:
        lock = asyncio.Lock()
        _HEALTH_CHECK_CACHE_LOCKS[check_name] = lock
    return lock


async def _run_health_check_with_cache(
    check_name: str,
    health_check: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    ttl_seconds = config.HEALTH_CHECK_CACHE_TTL_SECONDS
    if ttl_seconds <= 0:
        result = await health_check()
        checked_at = _health_check_checked_at(time.time())
        return _health_check_response(result, cached=False, checked_at=checked_at)

    now_monotonic = time.monotonic()
    cached_result = await _health_check_cache_hit(check_name, now_monotonic)
    if cached_result is not None:
        return cached_result

    async with _health_check_lock(check_name):
        now_monotonic = time.monotonic()
        cached_result = await _health_check_cache_hit(check_name, now_monotonic)
        if cached_result is not None:
            return cached_result

        result = await health_check()
        checked_at = _health_check_checked_at(time.time())

        # 1. Update in-memory cache
        _HEALTH_CHECK_CACHE[check_name] = {
            "result": dict(result),
            "checked_at": checked_at,
            "checked_monotonic": now_monotonic,
        }

        # 2. Update Redis cache (only if Redis queue is enabled)
        if config.QUEUE_BACKEND == "redis":
            try:
                redis_key = f"{REDIS_HEALTH_CACHE_PREFIX}:{check_name}"
                payload = json.dumps({
                    "result": dict(result),
                    "checked_at": checked_at,
                })
                await redis_client.setex(redis_key, config.HEALTH_CHECK_CACHE_TTL_SECONDS, payload)
            except Exception:
                logger.warning("Failed to update Redis health cache for %s", check_name)

        return _health_check_response(result, cached=False, checked_at=checked_at)


async def _embedding_health_check() -> dict:
    from services.embedding_service import probe_embedding_health

    t0 = time.monotonic()
    try:
        await asyncio.wait_for(
            probe_embedding_health("health check"),
            timeout=float(config.EMBEDDING_HEALTH_CHECK_TIMEOUT_SEC),
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"status": "ok", "latency_ms": latency_ms}
    except asyncio.TimeoutError:
        return {"status": "error", "error": "timeout"}
    except Exception as e:
        logger.warning("Embedding health check failed", exc_info=True)
        return {"status": "error", "error": _classify_provider_exception(e)}


def _llm_error_code_from_answer_text(text: str) -> str | None:
    """Map generate_answer error strings to short health-check codes."""
    from services.answer_service import (
        LLM_MSG_INVALID_API_KEY,
        LLM_MSG_MISSING_API_KEY,
        LLM_MSG_RATE_LIMIT,
        LLM_MSG_TIMEOUT,
    )

    if text == LLM_MSG_MISSING_API_KEY:
        return "api_key_missing"
    if text == LLM_MSG_INVALID_API_KEY:
        return "api_key_invalid"
    if text == LLM_MSG_RATE_LIMIT:
        return "rate_limited"
    if text == LLM_MSG_TIMEOUT:
        return "timeout"
    if text.startswith("LLM request failed") or text.startswith("LLM service is not available"):
        return "error"
    return None


async def _llm_health_check() -> dict:
    from services.answer_service import probe_llm_health

    t0 = time.monotonic()
    try:
        answer, _, _ = await asyncio.wait_for(
            probe_llm_health("health check", "context: ok"),
            timeout=float(config.LLM_HEALTH_CHECK_TIMEOUT_SEC),
        )
    except asyncio.TimeoutError:
        return {"status": "error", "error": "timeout"}
    except Exception as e:
        logger.warning("LLM health check failed", exc_info=True)
        return {"status": "error", "error": _classify_provider_exception(e)}

    err_code = _llm_error_code_from_answer_text(answer)
    if err_code is not None:
        return {"status": "error", "error": err_code}

    latency_ms = int((time.monotonic() - t0) * 1000)
    return {"status": "ok", "latency_ms": latency_ms}


async def _redis_health_check() -> dict:
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(redis_client.ping(), timeout=2.0)
        latency_ms = int((time.monotonic() - t0) * 1000)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        logger.warning("Redis health check failed", exc_info=True)
        return {"status": "error", "error": _classify_redis_exception(e)}

def _overall_status(db_ok: bool, embedding_ok: bool, llm_ok: bool, redis_ok: bool) -> str:
    if not db_ok or not redis_ok:
        return "unhealthy"
    if embedding_ok and llm_ok:
        return "healthy"
    return "degraded"


def _build_payload(
    *,
    db_ok: bool,
    documents_indexed: int | None,
    memory_pct: int,
    uptime_str: str,
    version: str,
    queue_pending: int | None,
    workers_active: int | None,
    embedding_health: dict,
    llm_health: dict,
    redis_health: dict | None,
) -> dict:
    db_component = "connected" if db_ok else "disconnected"
    embedding_ok = embedding_health.get("status") == "ok"
    llm_ok = llm_health.get("status") == "ok"
    
    redis_ok = True
    queue_component = "memory"
    if config.QUEUE_BACKEND == "redis":
        queue_component = "redis (connected)" if redis_health and redis_health.get("status") == "ok" else "redis (disconnected)"
        redis_ok = redis_health.get("status") == "ok" if redis_health else False
        
    embeddings_component = "ok" if embedding_ok else "degraded"
    llm_component = "ok" if llm_ok else "degraded"
    
    payload = {
        "status": _overall_status(db_ok, embedding_ok, llm_ok, redis_ok),
        "components": {
            "api": "online",
            "database": db_component,
            "queue": queue_component,
            "embeddings": embeddings_component,
            "llm": llm_component,
        },
        "health_checks": {
            "embedding": embedding_health,
            "llm": llm_health,
        },
        "metrics": {
            "document_queue": queue_pending,
            "workers_active": workers_active,
            "memory_usage": memory_pct,
            "documents_indexed": documents_indexed,
            "total_queries": None,
        },
        "uptime": uptime_str,
        "version": version,
    }
    
    if config.QUEUE_BACKEND == "redis" and redis_health:
        payload["health_checks"]["redis"] = redis_health
        
    return payload


def _format_ascii(data: dict) -> str:
    c = data["components"]
    m = data["metrics"]
    hc = data.get("health_checks") or {}
    emb_h = hc.get("embedding") or {}
    llm_h = hc.get("llm") or {}
    inner = 50  # text between "║  " and closing "║"

    def row(s: str) -> str:
        return "║  " + s[:inner].ljust(inner) + "║"

    db_line = "🟢 Database: Connected" if c["database"] == "connected" else "🔴 Database: Disconnected"
    
    q_line = "🟢 Queue: Memory"
    if config.QUEUE_BACKEND == "redis":
        if "connected" in c.get("queue", ""):
            q_line = f"🟢 Queue: Redis Connected ({hc.get('redis', {}).get('latency_ms', 0)}ms)"
        else:
            q_line = "🔴 Queue: Redis Disconnected"
            
    if emb_h.get("status") == "ok":
        emb_line = f"🟢 Embeddings: OK ({emb_h['latency_ms']}ms)"
    else:
        emb_err = emb_h.get("error", "error")
        emb_line = f"🔴 Embeddings: Degraded ({emb_err})"
    if llm_h.get("status") == "ok":
        llm_line = f"🟢 LLM Service: OK ({llm_h['latency_ms']}ms)"
    else:
        llm_err = llm_h.get("error", "error")
        llm_line = f"🔴 LLM Service: Degraded ({llm_err})"
    mem = m["memory_usage"]
    docs = m["documents_indexed"]
    docs_str = f"{docs:,}" if docs is not None else "—"
    q_cur = m["document_queue"]
    q_max = config.QUEUE_MAX_SIZE
    if q_cur is None:
        queue_line = "📊 Queue: — unavailable"
    else:
        queue_bar = _bar(q_cur, q_max)
        queue_line = f"📊 Queue: {queue_bar} {q_cur}/{q_max} pending"
    mem_bar = _bar_percent(mem)
    w_active = m["workers_active"]
    w_cap = config.QUEUE_WORKER_COUNT
    if w_active is None:
        workers_line = f"⚙️ Workers Active (this process): —/{w_cap}"
    else:
        workers_line = f"⚙️ Workers Active (this process): {w_active}/{w_cap}"

    lines = [
        "╔════════════════════════════════════════════════════╗",
        row("CHATVECTOR-AI SYSTEM STATUS"),
        "╠════════════════════════════════════════════════════╣",
        row("🟢 API Server: ONLINE"),
        row(db_line),
        row(q_line),
        row(emb_line),
        row(llm_line),
        row(""),
        row(queue_line),
        row(workers_line),
        row(f"💾 Memory Usage:   {mem_bar} {mem}%"),
        row(f"📁 Documents Indexed: {docs_str}"),
        row("💬 Total Queries:   — (not tracked)"),
        row(""),
        row(f"⏱ Uptime: {data['uptime']}"),
        row(f"🏷 Version: {data['version']}"),
        "╚════════════════════════════════════════════════════╝",
    ]
    return "\n".join(lines)

def _status_fallback_health_dict(exc: BaseException, label: str) -> dict:
    logger.exception("%s health check raised unexpectedly", label)
    return {
        "status": "error",
        "error": "error",
        "cached": False,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

@router.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    """Lightweight liveness check for container orchestration."""
    return {"status": "ok"}

@router.get("/status")
@limiter.limit(config.RATE_LIMIT_STATUS)
async def status(request: Request, auth: AuthContext = Depends(require_auth)):
    """Authenticated system status.

    ``metrics.documents_indexed`` counts documents for the authenticated tenant only.
    ``metrics.document_queue`` is an API-instance / shared-worker queue depth metric,
    not tenant-scoped.
    """
    from core.auth import require_current_tenant

    tenant_id = require_current_tenant(auth)
    start = getattr(request.app.state, "start_time", time.time())
    
    tasks = [
        _database_connected_and_document_count(tenant_id),
        _run_health_check_with_cache("embedding", _embedding_health_check),
        _run_health_check_with_cache("llm", _llm_health_check)
    ]
    
    if config.QUEUE_BACKEND == "redis":
        tasks.append(_run_health_check_with_cache("redis", _redis_health_check))
        
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    db_result = results[0]
    embedding_result = results[1]
    llm_result = results[2]
    redis_result = results[3] if config.QUEUE_BACKEND == "redis" else None

    if isinstance(db_result, BaseException):
        logger.exception("Database health check raised unexpectedly")
        db_ok, doc_count = False, None
    else:
        db_ok, doc_count = db_result

    if isinstance(embedding_result, BaseException):
        embedding_health = _status_fallback_health_dict(embedding_result, "Embedding")
    else:
        embedding_health = embedding_result

    if isinstance(llm_result, BaseException):
        llm_health = _status_fallback_health_dict(llm_result, "LLM")
    else:
        llm_health = llm_result
        
    redis_health = None
    if redis_result is not None:
        if isinstance(redis_result, BaseException):
            redis_health = _status_fallback_health_dict(redis_result, "Redis")
        else:
            redis_health = redis_result

    memory_pct = _process_memory_percent()
    version = _read_version()
    uptime_str = _format_uptime(start)
    q_pending, workers_active = await _queue_metrics()

    payload = _build_payload(
        db_ok=db_ok,
        documents_indexed=doc_count,
        memory_pct=memory_pct,
        uptime_str=uptime_str,
        version=version,
        queue_pending=q_pending,
        workers_active=workers_active,
        embedding_health=embedding_health,
        llm_health=llm_health,
        redis_health=redis_health,
    )

    if _is_browser(request):
        ascii_block = _format_ascii(payload)
        return HTMLResponse(
            content=f'<pre style="font-family: monospace; white-space: pre;">{ascii_block}</pre>',
            media_type="text/html; charset=utf-8",
        )
    return payload

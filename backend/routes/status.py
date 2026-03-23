import logging
import os
import time
from pathlib import Path
from typing import Any, cast

import psutil
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

import db
from core.config import config
from core.models import Document as DocumentModel
from db.sqlalchemy_service import SQLAlchemyService
from db.supabase_service import SupabaseService
from routes.root import _is_browser
from services.queue_service import ingestion_queue

logger = logging.getLogger(__name__)

router = APIRouter()

BACKEND_ROOT = Path(__file__).resolve().parent.parent
_BAR_WIDTH = 10


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


def _workers_active_count() -> int:
    iq = ingestion_queue
    getter = getattr(iq, "active_worker_count", None)
    if callable(getter):
        try:
            return int(cast(Any, getter()))
        except (TypeError, ValueError):
            pass
    return len([w for w in iq._workers if not w.done()])


async def _database_connected_and_document_count() -> tuple[bool, int | None]:
    service = db.get_db_service()
    if isinstance(service, SQLAlchemyService):
        try:
            async with service.async_session() as session:
                await session.execute(text("SELECT 1"))
                count = await session.scalar(select(func.count()).select_from(DocumentModel))
            return True, int(count or 0)
        except (SQLAlchemyError, OSError) as exc:
            logger.warning("Database health check failed: %s", exc)
            return False, None
        except Exception:
            logger.exception("Unexpected error during database health check")
            return False, None

    if isinstance(service, SupabaseService):

        async def _ping_and_count():
            from core.clients import supabase_client

            def _op():
                return (
                    supabase_client.table("documents")
                    .select("id", count="exact")
                    .limit(0)
                    .execute()
                )

            return await service._run_io(_op, "status_documents_count")

        try:
            result = await _ping_and_count()
            raw = getattr(result, "count", None)
            if raw is not None:
                return True, int(raw)
            if result.data is not None:
                return True, len(result.data)
            return True, 0
        except Exception:
            logger.exception("Supabase health check failed")
            return False, None

    logger.error("Unknown database service type for status: %s", type(service))
    return False, None


def _overall_status(db_ok: bool) -> str:
    return "healthy" if db_ok else "degraded"


def _build_payload(
    *,
    db_ok: bool,
    documents_indexed: int | None,
    memory_pct: int,
    uptime_str: str,
    version: str,
    queue_pending: int,
    queue_max: int,
    workers_active: int,
) -> dict:
    db_component = "connected" if db_ok else "disconnected"
    return {
        "status": _overall_status(db_ok),
        "components": {
            "api": "online",
            "database": db_component,
            "embeddings": "not_monitored",
            "llm": "not_monitored",
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


def _format_ascii(data: dict) -> str:
    c = data["components"]
    m = data["metrics"]
    inner = 50  # text between "║  " and closing "║"

    def row(s: str) -> str:
        return "║  " + s[:inner].ljust(inner) + "║"

    db_line = "🟢 Database: Connected" if c["database"] == "connected" else "🔴 Database: Disconnected"
    mem = m["memory_usage"]
    docs = m["documents_indexed"]
    docs_str = f"{docs:,}" if docs is not None else "—"
    q_cur = m["document_queue"]
    q_max = config.QUEUE_MAX_SIZE
    queue_bar = _bar(q_cur, q_max)
    mem_bar = _bar_percent(mem)
    w_active = m["workers_active"]
    w_cap = config.QUEUE_WORKER_COUNT

    lines = [
        "╔════════════════════════════════════════════════════╗",
        row("CHATVECTOR-AI SYSTEM STATUS"),
        "╠════════════════════════════════════════════════════╣",
        row("🟢 API Server: ONLINE"),
        row(db_line),
        row("🟡 Embeddings: Not monitored"),
        row("🟡 LLM Service: Not monitored"),
        row(""),
        row(f"📊 Queue: {queue_bar} {q_cur}/{q_max} pending"),
        row(f"⚙️ Workers Active: {w_active}/{w_cap}"),
        row(f"💾 Memory Usage:   {mem_bar} {mem}%"),
        row(f"📁 Documents Indexed: {docs_str}"),
        row("💬 Total Queries:   — (not tracked)"),
        row(""),
        row(f"⏱ Uptime: {data['uptime']}"),
        row(f"🏷 Version: {data['version']}"),
        "╚════════════════════════════════════════════════════╝",
    ]
    return "\n".join(lines)


@router.get("/status")
async def status(request: Request):
    start = getattr(request.app.state, "start_time", time.time())
    db_ok, doc_count = await _database_connected_and_document_count()
    memory_pct = _process_memory_percent()
    version = _read_version()
    uptime_str = _format_uptime(start)
    q_pending = ingestion_queue.queue_size()
    q_max = config.QUEUE_MAX_SIZE
    workers_active = _workers_active_count()

    payload = _build_payload(
        db_ok=db_ok,
        documents_indexed=doc_count,
        memory_pct=memory_pct,
        uptime_str=uptime_str,
        version=version,
        queue_pending=q_pending,
        queue_max=q_max,
        workers_active=workers_active,
    )

    if _is_browser(request):
        ascii_block = _format_ascii(payload)
        return HTMLResponse(
            content=f'<pre style="font-family: monospace; white-space: pre;">{ascii_block}</pre>',
            media_type="text/html; charset=utf-8",
        )
    return payload

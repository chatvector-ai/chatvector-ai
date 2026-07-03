import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth import AuthContext, require_auth
from core.config import config
from middleware.rate_limit import limiter
from services.queue_service import ingestion_queue

logger = logging.getLogger(__name__)
router = APIRouter()

# =============================================================================
# SECURITY / OPS — READ BEFORE DEPLOYMENT
# -----------------------------------------------------------------------------
# GET /queue/stats returns internal operational metrics (queue depth, worker
# count, DLQ metadata). It is disabled when APP_ENV=production (404). In
# non-production environments it remains available for local debugging; gate
# further (auth, allowlist) if you run a shared staging environment.
# =============================================================================


@router.get("/queue/stats")
@limiter.limit(config.RATE_LIMIT_QUEUE_STATS)
def get_queue_stats(request: Request, auth: AuthContext = Depends(require_auth)):
    """
    Return live ingestion queue statistics and dead-letter queue entries.

    DLQ entries are scoped to the authenticated tenant; cross-tenant entries
    are not visible. File bytes are never exposed.

    This endpoint returns 404 in production (APP_ENV=production) — it is
    intended for local debugging only and must not be exposed on shared
    staging environments without additional access controls.
    """
    if config.APP_ENV.lower() == "production":
        raise HTTPException(status_code=404, detail="Not found")

    tenant_id = auth.tenant_id
    all_dlq = ingestion_queue.dlq_jobs()

    # Filter to entries belonging to the authenticated tenant only.
    # Entries with no tenant_id (from before this change was deployed) are
    # excluded from all filtered views to avoid cross-tenant leakage.
    tenant_dlq = [e for e in all_dlq if e.tenant_id == tenant_id]

    dlq_entries = [
        {
            "doc_id": entry.doc_id,
            "file_name": entry.file_name,
            "attempt": entry.attempt,
            "error": entry.error,
            "failed_at": entry.failed_at.isoformat(),
        }
        for entry in tenant_dlq
    ]

    return {
        "queue_size": ingestion_queue.queue_size(),
        "worker_count": ingestion_queue.active_worker_count(),
        "dlq_size": len(dlq_entries),
        "dlq": dlq_entries,
    }

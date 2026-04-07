import logging

from fastapi import APIRouter, Request

from core.config import config
from middleware.rate_limit import limiter
from services.queue_service import ingestion_queue

logger = logging.getLogger(__name__)
router = APIRouter()

# =============================================================================
# SECURITY / OPS WARNING — READ BEFORE DEPLOYMENT
# -----------------------------------------------------------------------------
# GET /queue/stats is UNAUTHENTICATED and returns internal operational metrics
# (queue depth, worker task count, dead-letter metadata). This is intended for
# trusted local or private-network debugging only. Before any public, shared, or
# multi-tenant deployment, this route MUST be gated (e.g. auth, admin-only
# network policy, reverse-proxy allowlist, or feature flag). Do not expose it to
# the open internet without explicit review.
# =============================================================================


@router.get("/queue/stats")
@limiter.limit(config.RATE_LIMIT_QUEUE_STATS)
def get_queue_stats(request: Request):
    """
    Return live ingestion queue statistics and dead-letter queue entries.

    DLQ entries include only lightweight metadata; file bytes are never exposed.
    """
    dlq_entries = [
        {
            "doc_id": entry.doc_id,
            "file_name": entry.file_name,
            "attempt": entry.attempt,
            "error": entry.error,
            "failed_at": entry.failed_at.isoformat(),
        }
        for entry in ingestion_queue.dlq_jobs()
    ]

    return {
        "queue_size": ingestion_queue.queue_size(),
        "worker_count": ingestion_queue.active_worker_count(),
        "dlq_size": len(dlq_entries),
        "dlq": dlq_entries,
    }

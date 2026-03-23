import logging

from fastapi import APIRouter

from services.queue_service import ingestion_queue

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/queue/stats")
def get_queue_stats():
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
        "worker_count": len(ingestion_queue._workers),
        "dlq_size": len(dlq_entries),
        "dlq": dlq_entries,
    }

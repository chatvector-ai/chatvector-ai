import logging

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from core.config import config
from middleware.rate_limit import limiter

import db
from services.ingestion_pipeline import IngestionPipeline, UploadPipelineError, _sanitize_filename
from services.queue_service import QueueFull, QueueJob, ingestion_queue

logger = logging.getLogger(__name__)
router = APIRouter()
ingestion_pipeline = IngestionPipeline()


def _http_error(
    status_code: int,
    code: str,
    stage: str,
    message: str,
    document_id: str | None = None,
    headers: dict | None = None,
) -> HTTPException:
    detail = {
        "code": code,
        "stage": stage,
        "message": message,
    }
    if document_id:
        detail["document_id"] = document_id
    return HTTPException(status_code=status_code, detail=detail, headers=headers)


@router.post("/upload", status_code=202)
@limiter.limit(config.RATE_LIMIT_UPLOAD)
async def upload(request: Request, file: UploadFile = File(...)):
    """
    Accept a file upload, validate it, and enqueue it for background processing.

    Returns immediately (< 500 ms) with the document ID and queue position so
    the client can poll /documents/{document_id}/status for progress.
    """
    doc_id: str | None = None

    try:
        safe_filename = _sanitize_filename(file.filename)
        file_bytes = await file.read()

        # Validate synchronously before touching the DB
        ingestion_pipeline.validate_file(file, file_bytes)

        # Persist the document record so the status endpoint works immediately
        doc_id = await db.create_document(safe_filename)
        await db.update_document_status(doc_id=doc_id, status="queued")

        job = QueueJob(
            doc_id=doc_id,
            file_name=safe_filename,
            content_type=file.content_type,
            file_bytes=file_bytes,
        )

        try:
            queue_position = await ingestion_queue.enqueue(job)
        except QueueFull:
            # Roll back the document record so the DB stays clean
            await db.update_document_status(
                doc_id=doc_id,
                status="failed",
                error={"stage": "queued", "message": "Queue is at capacity. Please retry later."},
            )
            raise _http_error(
                    status_code=503,
                    code="queue_full",
                    stage="queued",
                    message="The processing queue is currently full. Please try again later.",
                    document_id=doc_id,
                    headers={"Retry-After": "30"},
                )

        logger.info(
            f"Accepted upload {safe_filename!r} → document {doc_id} "
            f"at queue position {queue_position}"
        )

        return {
            "message": "Accepted",
            "document_id": doc_id,
            "status": "queued",
            "queue_position": queue_position,
            "status_endpoint": f"/documents/{doc_id}/status",
        }

    except HTTPException:
        raise

    except UploadPipelineError as e:
        if doc_id and not e.document_id:
            e.document_id = doc_id
        logger.warning(
            f"Upload validation failed at stage={e.stage}: {e.message}"
        )
        raise _http_error(
            status_code=e.status_code,
            code=e.code,
            stage=e.stage,
            message=e.message,
            document_id=getattr(e, "document_id", None),
        )

    except Exception as e:
        if doc_id:
            await db.update_document_status(
                doc_id=doc_id,
                status="failed",
                error={
                    "stage": "queued", 
                    "code": "upload_failed", 
                    "message": "An unexpected error occurred during upload."
                },
            )
        logger.error(f"Unexpected error during upload of {safe_filename!r}: {e}")
        raise _http_error(
            status_code=500,
            code="upload_failed",
            stage="queued",
            message="Upload failed. Please try again.",
            document_id=doc_id,
        )

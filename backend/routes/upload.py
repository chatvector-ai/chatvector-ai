import logging

import asyncio
from fastapi import APIRouter, File, HTTPException, UploadFile

import db
from services.ingestion_pipeline import IngestionPipeline, UploadPipelineError
from services.queue_service import QueueJob, ingestion_queue

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
async def upload(file: UploadFile = File(...)):
    """
    Accept a file upload, validate it, and enqueue it for background processing.

    Returns immediately (< 500 ms) with the document ID and queue position so
    the client can poll /documents/{document_id}/status for progress.
    """
    doc_id: str | None = None

    try:
        file_bytes = await file.read()

        # Validate synchronously before touching the DB
        ingestion_pipeline.validate_file(file, file_bytes)

        # Persist the document record so the status endpoint works immediately
        doc_id = await db.create_document(file.filename)
        await db.update_document_status(doc_id=doc_id, status="queued")

        job = QueueJob(
            doc_id=doc_id,
            file_name=file.filename,
            content_type=file.content_type,
            file_bytes=file_bytes,
        )

        try:
            queue_position = await ingestion_queue.enqueue(job)
        except asyncio.QueueFull:
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
            f"Accepted upload {file.filename!r} → document {doc_id} "
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
                error={"stage": "queued", "message": str(e)[:500]},
            )
        logger.error(f"Unexpected error during upload of {file.filename!r}: {e}")
        raise _http_error(
            status_code=500,
            code="upload_failed",
            stage="queued",
            message="Upload failed. Please try again.",
            document_id=doc_id,
        )

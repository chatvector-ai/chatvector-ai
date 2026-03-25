import logging

from fastapi import APIRouter, HTTPException, Response

import db
from services.queue_service import ingestion_queue

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/documents/{document_id}/status")
async def get_document_status(document_id: str):
    status_payload = await db.get_document_status(document_id)
    if not status_payload:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": "Document not found.",
                "document_id": document_id,
            },
        )

    response: dict = {
        "document_id": status_payload["document_id"],
        "status": status_payload.get("status"),
        "chunks": status_payload.get("chunks"),
        "created_at": status_payload.get("created_at"),
        "updated_at": status_payload.get("updated_at"),
    }

    if status_payload.get("error") is not None:
        response["error"] = status_payload["error"]

    if status_payload.get("status") == "queued":
        queue_pos = ingestion_queue.queue_position(document_id)
        if queue_pos is not None:
            response["queue_position"] = queue_pos

    return response


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(document_id: str):
    status_payload = await db.get_document_status(document_id)
    if not status_payload:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": "Document not found.",
                "document_id": document_id,
            },
        )
    
    status = status_payload.get("status")
    if status in {"queued", "extracting", "embedding"}:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_processing",
                "message": f"Document cannot be deleted while in '{status}' state.",
                "document_id": document_id,
            },
        )

    await db.delete_document(document_id)
    return Response(status_code=204)

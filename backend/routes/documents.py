import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.auth import AuthContext, get_current_tenant, require_auth
from core.config import config
from middleware.rate_limit import limiter

import db
from core.config import STALE_INGESTION_STATUSES
from services.queue_service import ingestion_queue

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/documents/{document_id}/status")
@limiter.limit(config.RATE_LIMIT_DOCUMENT_STATUS)
async def get_document_status(request: Request, document_id: UUID, auth: AuthContext = Depends(require_auth)):
    status_payload = await db.get_document_status(str(document_id), tenant_id=get_current_tenant(auth))
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
        "document_id": str(document_id),
        "status": status_payload.get("status"),
        "chunks": status_payload.get("chunks"),
        "created_at": status_payload.get("created_at"),
        "updated_at": status_payload.get("updated_at"),
    }

    if status_payload.get("error") is not None:
        response["error"] = status_payload["error"]

    if status_payload.get("status") == "queued":
        queue_pos = ingestion_queue.queue_position(str(document_id))
        if queue_pos is not None:
            response["queue_position"] = queue_pos

    return response


@router.delete("/documents/{document_id}", status_code=204)
@limiter.limit(config.RATE_LIMIT_DOCUMENT_DELETE)
async def delete_document(request: Request, document_id: UUID, auth: AuthContext = Depends(require_auth)):
    status_payload = await db.get_document_status(str(document_id), tenant_id=get_current_tenant(auth))
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
    
    # Jobs already picked up by a worker are tracked via status rather than the queue
    if status in STALE_INGESTION_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_processing",
                "message": f"Document cannot be deleted while in '{status}' state.",
                "document_id": str(document_id),
            },
        )

    if ingestion_queue.queue_position(str(document_id)) is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "document_queued",
                "message": "Document cannot be deleted while in the queue.",
                "document_id": str(document_id),
            },
        )

    await db.delete_document(str(document_id), tenant_id=get_current_tenant(auth))
    return Response(status_code=204)

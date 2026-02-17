import logging

from fastapi import APIRouter, HTTPException

import db

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

    return status_payload

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import db
from core.auth import AuthContext, require_auth, require_current_tenant
from core.config import config
from core.session import NEW_SESSION_LABEL, Session
from services import session_service
from services.idempotency import (
    ROUTE_SESSION_CREATE,
    begin_idempotency,
    complete_idempotent_http_exception,
    parse_idempotency_key,
    session_create_fingerprint,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class SessionCreateRequest(BaseModel):
    session_id: Optional[str] = Field(None, min_length=1, max_length=255)


class SessionResponse(BaseModel):
    id: str
    tenant_id: Optional[str] = None
    created_at: str
    last_active: str
    metadata: dict
    document_ids: list[str]
    display_label: str


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


class SessionHistoryMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: Optional[str] = None
    sources: Optional[list] = None


class SessionHistoryResponse(BaseModel):
    messages: list[SessionHistoryMessageResponse]


def _format_session(session: Session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        tenant_id=session.tenant_id,
        created_at=session.created_at.isoformat(),
        last_active=session.last_active.isoformat(),
        metadata=session.metadata,
        document_ids=session.document_ids,
        display_label=session.display_label or NEW_SESSION_LABEL,
    )


@router.post("/sessions", status_code=201, response_model=SessionResponse)
async def create_session(
    request: Request,
    payload: SessionCreateRequest,
    auth: AuthContext = Depends(require_auth),
):
    tenant_id = require_current_tenant(auth)
    idempotency_lease = None
    try:
        fingerprint = session_create_fingerprint(session_id=payload.session_id)
        idempotency_key = parse_idempotency_key(request)
        idempotency_lease, replay = await begin_idempotency(
            tenant_id=tenant_id,
            route=ROUTE_SESSION_CREATE,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return replay

        session = await session_service.create_session(
            session_id=payload.session_id, tenant_id=tenant_id
        )
        response_body = _format_session(session).model_dump()
        await idempotency_lease.complete(201, response_body)
        return _format_session(session)
    except HTTPException as exc:
        if idempotency_lease is not None and idempotency_lease.active:
            await complete_idempotent_http_exception(idempotency_lease, exc)
        raise
    except ValueError as e:
        http_exc = HTTPException(status_code=409, detail=str(e))
        if idempotency_lease is not None and idempotency_lease.active:
            await complete_idempotent_http_exception(idempotency_lease, http_exc)
        raise http_exc from e
    except Exception:
        if idempotency_lease is not None and idempotency_lease.active:
            await idempotency_lease.abort()
        raise


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(auth: AuthContext = Depends(require_auth)):
    tenant_id = require_current_tenant(auth)
    sessions = await session_service.list_sessions(tenant_id=tenant_id)
    return SessionListResponse(sessions=[_format_session(s) for s in sessions])


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, auth: AuthContext = Depends(require_auth)):
    """
    Retrieve session metadata.
    
    Note: Reading a session mutates its `last_active` timestamp to track recent activity.
    """
    tenant_id = require_current_tenant(auth)
    session = await session_service.get_session(session_id=session_id, tenant_id=tenant_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _format_session(session)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, auth: AuthContext = Depends(require_auth)):
    tenant_id = require_current_tenant(auth)
    deleted = await session_service.delete_session(session_id=session_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str, auth: AuthContext = Depends(require_auth)):
    tenant_id = require_current_tenant(auth)
    session = await session_service.get_session(session_id=session_id, tenant_id=tenant_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await db.get_session_history(
        session_id=session_id,
        tenant_id=tenant_id,
        limit=config.MAX_SESSION_HISTORY_MESSAGES,
    )

    return SessionHistoryResponse(
        messages=[
            SessionHistoryMessageResponse(
                id=message["id"],
                role=message["role"],
                content=message["content"],
                created_at=message.get("created_at"),
                sources=message.get("sources"),
            )
            for message in messages
        ]
    )

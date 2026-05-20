import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthContext, get_current_tenant, require_auth
from core.session import Session
from services import session_service

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


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


def _format_session(session: Session) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        tenant_id=session.tenant_id,
        created_at=session.created_at.isoformat(),
        last_active=session.last_active.isoformat(),
        metadata=session.metadata,
        document_ids=session.document_ids,
    )


@router.post("/sessions", status_code=201, response_model=SessionResponse)
async def create_session(
    payload: SessionCreateRequest, auth: AuthContext = Depends(require_auth)
):
    tenant_id = get_current_tenant(auth)
    try:
        session = session_service.create_session(
            session_id=payload.session_id, tenant_id=tenant_id
        )
        return _format_session(session)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(auth: AuthContext = Depends(require_auth)):
    tenant_id = get_current_tenant(auth)
    sessions = session_service.list_sessions(tenant_id=tenant_id)
    return SessionListResponse(sessions=[_format_session(s) for s in sessions])


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, auth: AuthContext = Depends(require_auth)):
    """
    Retrieve session metadata.
    
    Note: Reading a session mutates its `last_active` timestamp to track recent activity.
    """
    tenant_id = get_current_tenant(auth)
    session = session_service.get_session(session_id=session_id, tenant_id=tenant_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _format_session(session)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, auth: AuthContext = Depends(require_auth)):
    tenant_id = get_current_tenant(auth)
    deleted = session_service.delete_session(session_id=session_id, tenant_id=tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

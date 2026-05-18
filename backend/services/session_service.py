import logging
from datetime import datetime, timezone
import uuid
from typing import Optional, Dict, List
from core.session import Session

logger = logging.getLogger(__name__)

# Lightweight in-memory store for Phase 3A foundation.
# In Phase 3B/C, this would move to Redis or PostgreSQL.
_SESSIONS: Dict[str, Session] = {}


def create_session(session_id: Optional[str] = None, tenant_id: Optional[str] = None) -> Session:
    new_id = session_id or str(uuid.uuid4())
    if new_id in _SESSIONS:
        raise ValueError(f"Session with id {new_id} already exists")
    
    new_session = Session(id=new_id, tenant_id=tenant_id)
    _SESSIONS[new_id] = new_session
    logger.info(f"Created new session: {new_id} (tenant={tenant_id})")
    return new_session


def get_session(session_id: str, tenant_id: Optional[str] = None) -> Optional[Session]:
    session = _SESSIONS.get(session_id)
    if session:
        # TODO(Phase 3B): Strict tenant isolation.
        # Currently, if tenant_id is None (from Phase 3A require_auth), isolation is bypassed.
        if tenant_id and session.tenant_id and session.tenant_id != tenant_id:
            logger.warning(
                f"Session {session_id} tenant mismatch: {session.tenant_id} vs {tenant_id}"
            )
            return None
        session.last_active = datetime.now(timezone.utc)
        return session
    return None


def list_sessions(tenant_id: Optional[str] = None) -> List[Session]:
    # TODO(Phase 3B): Strict tenant isolation.
    return [
        session for session in _SESSIONS.values()
        if not tenant_id or session.tenant_id == tenant_id
    ]


def delete_session(session_id: str, tenant_id: Optional[str] = None) -> bool:
    session = get_session(session_id, tenant_id)
    if session:
        del _SESSIONS[session_id]
        logger.info(f"Deleted session: {session_id}")
        return True
    return False


def get_or_create_session(
    session_id: Optional[str] = None, tenant_id: Optional[str] = None
) -> Session:
    """
    Retrieve an existing session or initialize a new one.

    If session_id is provided but not found, a new session is created with that ID.
    If session_id is missing, a random UUID is generated.
    """
    if session_id:
        session = get_session(session_id, tenant_id)
        if session:
            return session
    
    # If not found or not provided, create a new one (or recreate with the provided ID)
    try:
        return create_session(session_id, tenant_id)
    except ValueError:
        # Should not happen because get_session would have found it, unless tenant mismatch
        return create_session(None, tenant_id)


def reset_session(session_id: str) -> bool:
    """Remove a session from the store."""
    return delete_session(session_id)

import logging
from datetime import datetime, timezone
import uuid
from typing import Optional, Dict
from core.session import Session

logger = logging.getLogger(__name__)

# Lightweight in-memory store for Phase 3A foundation.
# In Phase 3B/C, this would move to Redis or PostgreSQL.
_SESSIONS: Dict[str, Session] = {}


def get_or_create_session(
    session_id: Optional[str] = None, tenant_id: Optional[str] = None
) -> Session:
    """
    Retrieve an existing session or initialize a new one.

    If session_id is provided but not found, a new session is created with that ID.
    If session_id is missing, a random UUID is generated.
    """
    if session_id and session_id in _SESSIONS:
        session = _SESSIONS[session_id]
        session.last_active = datetime.now(timezone.utc)

        # Simple tenant verification if both are present
        if tenant_id and session.tenant_id and session.tenant_id != tenant_id:
            logger.warning(
                f"Session {session_id} tenant mismatch: {session.tenant_id} vs {tenant_id}"
            )

        return session

    # Create new session
    new_id = session_id or str(uuid.uuid4())
    new_session = Session(id=new_id, tenant_id=tenant_id)
    _SESSIONS[new_id] = new_session
    logger.info(f"Created new session: {new_id} (tenant={tenant_id})")
    return new_session


def reset_session(session_id: str) -> bool:
    """Remove a session from the store."""
    if session_id in _SESSIONS:
        del _SESSIONS[session_id]
        return True
    return False

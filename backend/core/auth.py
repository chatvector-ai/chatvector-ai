from typing import Optional
from pydantic import BaseModel


class AuthContext(BaseModel):
    """
    Authentication context for Phase 3 multi-tenancy and sessions.
    """
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None


def require_auth() -> AuthContext:
    """
    Phase 3 placeholder.

    Will return tenant context once authentication is implemented.
    """
    return AuthContext(tenant_id=None)


def get_current_tenant(auth: AuthContext) -> Optional[str]:
    """
    Helper function to extract the tenant ID from the authentication context.
    """
    return auth.tenant_id

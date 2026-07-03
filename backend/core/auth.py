from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel


class AuthContext(BaseModel):
    """Authentication context resolved for every protected request."""

    tenant_id: Optional[str] = None
    api_key_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None


def _401(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_auth(request: Request) -> AuthContext:
    """FastAPI dependency that resolves the caller's tenant from a Bearer API key.

    Development / test bypass
    ─────────────────────────
    When APP_ENV is 'development' or 'test', authentication is skipped and
    the request is associated with the tenant named by the DEV_TENANT_ID
    environment variable (default: "dev").  This keeps local development and
    the existing test suite working without API keys.

    Production
    ──────────
    Requires a valid ``Authorization: Bearer cv_live_<prefix>.<secret>``
    header.  Any missing, malformed, or invalid key results in a 401.
    """
    from core.config import config

    # ── Non-production bypass ────────────────────────────────────────────────
    if config.APP_ENV.lower() in ("development", "test"):
        dev_tenant = os.getenv("DEV_TENANT_ID", "dev")
        return AuthContext(tenant_id=dev_tenant)

    # ── Parse the Authorization header ──────────────────────────────────────
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        raise _401("missing_credentials", "Authorization header is required.")

    if not auth_header.startswith("Bearer "):
        raise _401(
            "malformed_credentials",
            "Authorization header must use the Bearer scheme.",
        )

    raw_key = auth_header[len("Bearer "):]
    if not raw_key:
        raise _401("malformed_credentials", "Bearer token must not be empty.")

    # ── Validate the key ────────────────────────────────────────────────────
    from services.api_key_service import validate_api_key

    result = await validate_api_key(raw_key)
    if result is None:
        raise _401("invalid_api_key", "API key is invalid or has been revoked.")

    tenant_id, api_key_id = result
    return AuthContext(tenant_id=tenant_id, api_key_id=api_key_id)


def get_current_tenant(auth: AuthContext) -> Optional[str]:
    """Extract tenant ID from the authentication context."""
    return auth.tenant_id

"""Rate limiting setup using slowapi."""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# request.state attribute set by require_auth before rate-limit checks run.
TENANT_ID_STATE_KEY = "tenant_id"


def get_rate_limit_key(request: Request) -> str:
    """Return the rate-limit bucket key for the current request.

    Uses the authenticated tenant when available (set on ``request.state``
    by ``require_auth``). In development/test with ``RATE_LIMIT_DEV_IP_FALLBACK``
    enabled, falls back to client IP when no tenant is present. Production
    never silently falls back to IP — unauthenticated requests share an
    ``unauthenticated`` bucket (they still fail auth separately).
    """
    from core.config import config

    tenant_id = getattr(request.state, TENANT_ID_STATE_KEY, None)
    if tenant_id:
        return f"tenant:{tenant_id}"

    if (
        config.RATE_LIMIT_DEV_IP_FALLBACK
        and config.APP_ENV.lower() in ("development", "test")
    ):
        return f"ip:{get_remote_address(request)}"

    return "unauthenticated"


def _rate_limit_key_type(limit_key: str) -> str:
    if limit_key.startswith("tenant:"):
        return "tenant"
    if limit_key.startswith("ip:"):
        return "ip"
    return "unauthenticated"


limiter = Limiter(key_func=get_rate_limit_key)


async def rate_limit_exceeded_handler(
    request: Request, _exc: RateLimitExceeded
) -> JSONResponse:
    limit_key = get_rate_limit_key(request)
    tenant_id = getattr(request.state, TENANT_ID_STATE_KEY, None)
    logger.warning(
        "Rate limit exceeded",
        extra={
            "event": "rate_limited",
            "tenant_id": tenant_id,
            "key_type": _rate_limit_key_type(limit_key),
            "path": request.url.path,
            "method": request.method,
        },
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "code": "rate_limited",
                "message": "Too many requests. Please slow down.",
            }
        },
        headers={"Retry-After": "60"},
    )

from fastapi import APIRouter, Depends, Request

from core.auth import AuthContext, require_auth, require_current_tenant
from core.config import config
from middleware.rate_limit import limiter
from services.retrieval_presets import build_retrieval_preset_discovery

router = APIRouter()


@router.get("/retrieval/presets")
@limiter.limit(config.RATE_LIMIT_DOCUMENT_STATUS)
async def list_retrieval_presets(
    request: Request, auth: AuthContext = Depends(require_auth)
):
    """List loaded retrieval preset names and configured reranker identifiers."""
    require_current_tenant(auth)
    return build_retrieval_preset_discovery()

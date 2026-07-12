import logging
from typing import Literal, Optional
from uuid import UUID

import db
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.auth import AuthContext, require_auth, require_current_tenant
from core.config import config
from middleware.rate_limit import limiter
from pydantic import BaseModel, Field

from services.chat_service import (
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
)
from services.session_service import get_or_create_session, register_session_document
from services.tenant_registry import register_tenant_document

logger = logging.getLogger(__name__)
router = APIRouter()

RetrievalScopeParam = Literal["session", "tenant"]


async def _assert_document_owned(doc_id: str, tenant_id: str) -> None:
    """Raise 404 if the document does not exist or belongs to a different tenant."""
    doc = await db.get_document(doc_id, tenant_id=tenant_id)
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": "Document not found.",
                "document_id": doc_id,
            },
        )


class ChatBatchItem(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    doc_ids: list[UUID] = Field(..., min_length=1)
    match_count: int = Field(default=5, ge=1, le=20)
    session_id: Optional[str] = None
    scope: RetrievalScopeParam = "session"


class ChatBatchRequest(BaseModel):
    queries: list[ChatBatchItem] = Field(..., min_length=1, max_length=20)
    session_id: Optional[str] = None
    scope: RetrievalScopeParam = "session"


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    doc_id: UUID
    match_count: int = Field(default=5, ge=1, le=20)
    session_id: Optional[str] = None
    scope: RetrievalScopeParam = "session"


@router.post("/chat")
@limiter.limit(config.RATE_LIMIT_CHAT)
async def chat(request: Request, payload: ChatRequest, auth: AuthContext = Depends(require_auth)):
    logger.info(f"Chat request received for document {payload.doc_id}")

    doc_id_str = str(payload.doc_id)
    tenant_id = require_current_tenant(auth)
    await _assert_document_owned(doc_id_str, tenant_id)

    # Initialize or retrieve session
    session = await get_or_create_session(
        session_id=payload.session_id, tenant_id=tenant_id
    )
    await register_session_document(session.id, doc_id_str, tenant_id)
    register_tenant_document(tenant_id, doc_id_str)

    return await answer_question_for_document(
        question=payload.question,
        doc_id=doc_id_str,
        match_count=payload.match_count,
        auth=auth,
        session_id=session.id,
        scope=payload.scope,
    )


@router.post("/chat/stream")
@limiter.limit(config.RATE_LIMIT_CHAT)
async def chat_stream(request: Request, payload: ChatRequest, auth: AuthContext = Depends(require_auth)):
    """Stream a chat answer as Server-Sent Events (SSE).

    Requires ``ENABLE_STREAMING=true``. Event contract:

    - ``token`` — incremental answer text; ``data`` is a JSON-encoded string
      (unchanged from earlier clients).
    - ``complete`` — final structured payload with ``sources``, ``latency_ms``,
      ``model``, and ``session_id``.
    - ``done`` — legacy completion marker ``[DONE]`` (deprecated; retained for
      backward compatibility).
    - ``error`` — structured JSON object ``{"type": "error", "code": "...", "message": "..."}``.

    Interrupted streams (client disconnect, cancellation, or provider failure
    mid-stream) do not persist assistant messages. Successful streams persist
    user and assistant messages after the ``complete`` event is emitted.
    """
    if not config.ENABLE_STREAMING:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "streaming_disabled",
                "message": "Streaming responses are currently disabled.",
            },
        )

    logger.info(f"Chat stream request received for document {payload.doc_id}")

    doc_id_str = str(payload.doc_id)
    tenant_id = require_current_tenant(auth)
    await _assert_document_owned(doc_id_str, tenant_id)

    # Initialize or retrieve session
    session = await get_or_create_session(
        session_id=payload.session_id, tenant_id=tenant_id
    )
    await register_session_document(session.id, doc_id_str, tenant_id)
    register_tenant_document(tenant_id, doc_id_str)

    return StreamingResponse(
        answer_question_stream_for_document(
            question=payload.question,
            doc_id=doc_id_str,
            match_count=payload.match_count,
            auth=auth,
            session_id=session.id,
            scope=payload.scope,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/batch")
@limiter.limit(config.RATE_LIMIT_CHAT_BATCH)
async def chat_batch(request: Request, payload: ChatBatchRequest, auth: AuthContext = Depends(require_auth)):
    logger.info(f"Batch chat request received with {len(payload.queries)} queries")

    # Shared session for the batch if provided at top level, otherwise uses individual
    batch_session_id = payload.session_id

    tenant_id = require_current_tenant(auth)

    try:
        # Pre-process queries to inject session_id if missing
        processed_queries = []
        for q in payload.queries:
            q_dict = q.model_dump(mode="json")
            # Only keep per-item scope when explicitly provided by the caller.
            # When unset, let the batch-level `scope` take effect in the service.
            if "scope" not in q.model_fields_set:
                q_dict.pop("scope", None)
            q_session = await get_or_create_session(
                session_id=q.session_id or batch_session_id,
                tenant_id=tenant_id,
            )
            q_dict["session_id"] = q_session.id
            for doc_id in q.doc_ids:
                doc_id_str = str(doc_id)
                await _assert_document_owned(doc_id_str, tenant_id)
                await register_session_document(q_session.id, doc_id_str, tenant_id)
                register_tenant_document(tenant_id, doc_id_str)
            processed_queries.append(q_dict)

        results = await answer_questions_for_documents_batch(
            processed_queries,
            auth=auth,
            scope=payload.scope,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_batch_request",
                "message": str(e),
            },
        )

    success_count = sum(1 for item in results if item.get("status") == "ok")
    failure_count = len(results) - success_count

    return {
        "count": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
    }

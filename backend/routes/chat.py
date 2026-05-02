import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.auth import AuthContext, require_auth
from core.config import config
from middleware.rate_limit import limiter
from pydantic import BaseModel, Field

from services.chat_service import (
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
)
from services.session_service import get_or_create_session

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatBatchItem(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    doc_ids: list[UUID] = Field(..., min_length=1)
    match_count: int = Field(default=5, ge=1, le=20)
    session_id: Optional[str] = None


class ChatBatchRequest(BaseModel):
    queries: list[ChatBatchItem] = Field(..., min_length=1, max_length=20)
    session_id: Optional[str] = None


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    doc_id: UUID
    match_count: int = Field(default=5, ge=1, le=20)
    session_id: Optional[str] = None


@router.post("/chat")
@limiter.limit(config.RATE_LIMIT_CHAT)
async def chat(request: Request, payload: ChatRequest, auth: AuthContext = Depends(require_auth)):
    logger.info(f"Chat request received for document {payload.doc_id}")

    # Initialize or retrieve session
    session = get_or_create_session(
        session_id=payload.session_id, tenant_id=auth.tenant_id
    )

    return await answer_question_for_document(
        question=payload.question,
        doc_id=str(payload.doc_id),
        match_count=payload.match_count,
        auth=auth,
        session_id=session.id,
    )


@router.post("/chat/stream")
@limiter.limit(config.RATE_LIMIT_CHAT)
async def chat_stream(request: Request, payload: ChatRequest, auth: AuthContext = Depends(require_auth)):
    if not config.ENABLE_STREAMING:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "streaming_disabled",
                "message": "Streaming responses are currently disabled.",
            },
        )

    logger.info(f"Chat stream request received for document {payload.doc_id}")
    return StreamingResponse(
        answer_question_stream_for_document(
            question=payload.question,
            doc_id=str(payload.doc_id),
            match_count=payload.match_count,
            auth=auth,
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

    try:
        # Pre-process queries to inject session_id if missing
        processed_queries = []
        for q in payload.queries:
            q_dict = q.model_dump(mode="json")
            q_session = get_or_create_session(
                session_id=q.session_id or batch_session_id,
                tenant_id=auth.tenant_id,
            )
            q_dict["session_id"] = q_session.id
            processed_queries.append(q_dict)

        results = await answer_questions_for_documents_batch(
            processed_queries,
            auth=auth,
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

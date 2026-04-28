import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from core.config import config
from middleware.rate_limit import limiter
from pydantic import BaseModel, Field

from services.chat_service import (
    answer_question_for_document,
    answer_questions_for_documents_batch,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatBatchItem(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    doc_ids: list[UUID] = Field(..., min_length=1)
    match_count: int = Field(default=5, ge=1, le=20)


class ChatBatchRequest(BaseModel):
    queries: list[ChatBatchItem] = Field(..., min_length=1, max_length=20)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    doc_id: UUID
    match_count: int = Field(default=5, ge=1, le=20)


@router.post("/chat")
@limiter.limit(config.RATE_LIMIT_CHAT)
async def chat(request: Request, payload: ChatRequest):
    logger.info(f"Chat request received for document {payload.doc_id}")
    return await answer_question_for_document(
        question=payload.question,
        doc_id=str(payload.doc_id),
        match_count=payload.match_count,
    )


@router.post("/chat/batch")
@limiter.limit(config.RATE_LIMIT_CHAT_BATCH)
async def chat_batch(request: Request, payload: ChatBatchRequest):
    logger.info(f"Batch chat request received with {len(payload.queries)} queries")

    try:
        results = await answer_questions_for_documents_batch(
            [query.model_dump(mode="json") for query in payload.queries]
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


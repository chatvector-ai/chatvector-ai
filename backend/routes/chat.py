import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.chat_service import (
    answer_question_for_document,
    answer_questions_for_documents_batch,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatBatchItem(BaseModel):
    question: str = Field(..., min_length=1)
    doc_ids: list[str] = Field(..., min_length=1)
    match_count: int = Field(default=5, ge=1)


class ChatBatchRequest(BaseModel):
    queries: list[ChatBatchItem] = Field(..., min_length=1)


@router.post("/chat")
async def chat(question: str, doc_id: str, match_count: int = 5):
    logger.info(f"Chat request received for document {doc_id}")
    return await answer_question_for_document(
        question=question,
        doc_id=doc_id,
        match_count=match_count,
    )


@router.post("/chat/batch")
async def chat_batch(payload: ChatBatchRequest):
    logger.info(f"Batch chat request received with {len(payload.queries)} queries")

    try:
        results = await answer_questions_for_documents_batch(
            [query.model_dump() for query in payload.queries]
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_batch_request",
                "message": str(e),
            },
        )

    return {
        "count": len(results),
        "results": results,
    }


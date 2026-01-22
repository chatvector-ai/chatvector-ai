from fastapi import APIRouter
from backend.services.embedding_service import get_embedding
from backend.services.answer_service import generate_answer
from backend.services.db_service import locate_matching_chunks
from backend.services.context_service import build_context_from_chunks
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/chat")
async def chat(question: str, doc_id: str):   
    logger.info(f"Starting chat for file doc id {doc_id})")
    # step 1: Embed query
    query_embedding = await get_embedding(question)
    # step 2: vector search
    matching_chunks = await locate_matching_chunks(doc_id, query_embedding, match_count=5)
    # step 3: prepare context for llm
    context = build_context_from_chunks(matching_chunks)
    # step 4: generate answer
    answer = await generate_answer(question, context)
    logger.info(f"Answer generated successfully for doc id {doc_id}.")
    return {
        "question": question,
        "chunks": len(matching_chunks),
        "answer": answer
    }


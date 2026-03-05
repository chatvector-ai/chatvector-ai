import logging
import asyncio

from core.config import config
from db import find_similar_chunks
from services.context_service import build_context_from_chunks

logger = logging.getLogger(__name__)

_retrieval_limit = max(1, int(config.RETRIEVAL_MAX_CONCURRENCY))
_retrieval_semaphore = asyncio.Semaphore(_retrieval_limit)


def _get_retrieval_semaphore() -> asyncio.Semaphore:
    global _retrieval_limit, _retrieval_semaphore

    configured_limit = max(1, int(config.RETRIEVAL_MAX_CONCURRENCY))
    if configured_limit != _retrieval_limit:
        _retrieval_limit = configured_limit
        _retrieval_semaphore = asyncio.Semaphore(_retrieval_limit)

    return _retrieval_semaphore


async def get_embedding(text: str) -> list[float]:
    """
    Lazily import embedding dependency to keep module import side-effect free.
    """
    from services.embedding_service import get_embedding as _get_embedding

    return await _get_embedding(text)


async def generate_answer(question: str, context: str) -> str:
    """
    Lazily import answer dependency to keep module import side-effect free.
    """
    from services.answer_service import generate_answer as _generate_answer

    return await _generate_answer(question, context)


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Lazily import batch embedding dependency to keep module import side-effect free.
    """
    from services.embedding_service import get_embeddings as _get_embeddings

    return await _get_embeddings(texts)


def _normalize_doc_ids(doc_ids: list[str], *, query_index: int) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    empty_positions: list[int] = []
    duplicate_ids: list[str] = []

    for position, raw_doc_id in enumerate(doc_ids, start=1):
        doc_id = (raw_doc_id or "").strip()
        if not doc_id:
            empty_positions.append(position)
            continue
        if doc_id in seen:
            duplicate_ids.append(doc_id)
            continue

        seen.add(doc_id)
        normalized.append(doc_id)

    if empty_positions:
        raise ValueError(
            f"Query #{query_index} contains empty document IDs at positions {empty_positions}"
        )

    if duplicate_ids:
        duplicate_values = sorted(set(duplicate_ids))
        raise ValueError(
            f"Query #{query_index} contains duplicate doc IDs: {duplicate_values}"
        )

    return normalized


async def _retrieve_chunks_for_documents(
    doc_ids: list[str],
    query_embedding: list[float],
    match_count: int,
) -> list:
    retrieval_semaphore = _get_retrieval_semaphore()

    async def _search_one_document(doc_id: str) -> list:
        async with retrieval_semaphore:
            return await find_similar_chunks(
                doc_id=doc_id,
                query_embedding=query_embedding,
                match_count=match_count,
            )

    per_document_chunks = await asyncio.gather(
        *[_search_one_document(doc_id) for doc_id in doc_ids]
    )

    merged_chunks = []
    for chunks in per_document_chunks:
        merged_chunks.extend(chunks)

    return merged_chunks


async def answer_question_for_document(
    question: str,
    doc_id: str,
    match_count: int = 5,
) -> dict:
    """
    Orchestrate the chat flow for a single question/document pair.
    """
    logger.info(f"Starting chat for document {doc_id}")

    query_embedding = await get_embedding(question)
    matching_chunks = await _retrieve_chunks_for_documents(
        doc_ids=[doc_id],
        query_embedding=query_embedding,
        match_count=match_count,
    )
    context = build_context_from_chunks(matching_chunks)
    answer = await generate_answer(question, context)

    logger.info(f"Answer generated successfully for document {doc_id}")
    return {
        "question": question,
        "chunks": len(matching_chunks),
        "answer": answer,
    }


async def answer_questions_for_documents_batch(
    queries: list[dict],
) -> list[dict]:
    """
    Process multiple question/document retrieval requests in one call.
    """
    if not queries:
        return []

    if len(queries) > config.CHAT_BATCH_MAX_ITEMS:
        raise ValueError(
            f"Batch size {len(queries)} exceeds CHAT_BATCH_MAX_ITEMS={config.CHAT_BATCH_MAX_ITEMS}"
        )

    normalized_queries = []
    for index, query in enumerate(queries, start=1):
        question = (query.get("question") or "").strip()
        if not question:
            raise ValueError(f"Query #{index} has empty question")

        doc_ids = _normalize_doc_ids(query.get("doc_ids") or [], query_index=index)
        if not doc_ids:
            raise ValueError(f"Query #{index} has no valid document IDs")

        if len(doc_ids) > config.CHAT_MAX_DOC_IDS_PER_QUERY:
            raise ValueError(
                f"Query #{index} has {len(doc_ids)} doc IDs; limit is CHAT_MAX_DOC_IDS_PER_QUERY={config.CHAT_MAX_DOC_IDS_PER_QUERY}"
            )

        match_count = int(query.get("match_count", 5))
        if match_count < 1:
            raise ValueError(f"Query #{index} has invalid match_count={match_count}")

        normalized_queries.append(
            {
                "question": question,
                "doc_ids": doc_ids,
                "match_count": match_count,
            }
        )

    embeddings = await get_embeddings([q["question"] for q in normalized_queries])
    if len(embeddings) != len(normalized_queries):
        mismatch_message = (
            f"Embedding mismatch: got {len(embeddings)} embeddings for {len(normalized_queries)} queries"
        )
        logger.error(mismatch_message)
        return [
            {
                "status": "error",
                "question": query["question"],
                "doc_ids": query["doc_ids"],
                "chunks": 0,
                "error": {
                    "code": "embedding_mismatch",
                    "message": mismatch_message,
                },
            }
            for query in normalized_queries
        ]

    async def _process_query(query: dict, query_embedding: list[float]) -> dict:
        try:
            matching_chunks = await _retrieve_chunks_for_documents(
                doc_ids=query["doc_ids"],
                query_embedding=query_embedding,
                match_count=query["match_count"],
            )
            context = build_context_from_chunks(matching_chunks)
            answer = await generate_answer(query["question"], context)

            return {
                "status": "ok",
                "question": query["question"],
                "doc_ids": query["doc_ids"],
                "chunks": len(matching_chunks),
                "answer": answer,
            }
        except Exception as e:
            logger.exception(
                "Batch query failed for question='%s' doc_ids=%s",
                query["question"],
                query["doc_ids"],
            )
            return {
                "status": "error",
                "question": query["question"],
                "doc_ids": query["doc_ids"],
                "chunks": 0,
                "error": {
                    "code": "query_processing_failed",
                    "message": str(e),
                },
            }

    return await asyncio.gather(
        *[
            _process_query(query, embedding)
            for query, embedding in zip(normalized_queries, embeddings)
        ]
    )

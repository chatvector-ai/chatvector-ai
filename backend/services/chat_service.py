import logging
import asyncio
from typing import Optional

from core.config import config
from db import find_similar_chunks
from services.context_service import SessionContext, build_context_from_chunks
from services.query_service import transform_query

logger = logging.getLogger(__name__)


def _structured_error_from_llm_answer(answer: str) -> dict | None:
    """Map soft LLM failure strings from answer_service to {code, message}."""
    from services.answer_service import (
        LLM_MSG_INVALID_API_KEY,
        LLM_MSG_MISSING_API_KEY,
        LLM_MSG_RATE_LIMIT,
        LLM_MSG_TIMEOUT,
        LLM_MSG_UNEXPECTED,
    )

    exact_codes: list[tuple[str, str]] = [
        (LLM_MSG_MISSING_API_KEY, "llm_missing_api_key"),
        (LLM_MSG_INVALID_API_KEY, "llm_invalid_api_key"),
        (LLM_MSG_RATE_LIMIT, "llm_rate_limited"),
        (LLM_MSG_TIMEOUT, "llm_timeout_or_connection"),
        (LLM_MSG_UNEXPECTED, "llm_unexpected"),
    ]
    for msg, code in exact_codes:
        if answer == msg:
            return {"code": code, "message": msg}
    if answer.startswith("LLM service is not available") or answer.startswith(
        "LLM request failed"
    ):
        return {"code": "llm_error", "message": answer}
    return None

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


def _build_sources(chunks: list) -> list[dict]:
    """Extract citation metadata from retrieved chunks."""
    return [
        {
            "file_name": chunk.file_name,
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
        }
        for chunk in chunks
    ]


async def answer_question_for_document(
    question: str,
    doc_id: str,
    match_count: int = 5,
    session_context: Optional[SessionContext] = None,
) -> dict:
    """
    Orchestrate the chat flow for a single question/document pair.
    """
    logger.info(f"Starting chat for document {doc_id}")

    transformed_queries = await transform_query(question)
    query_embeddings = await get_embeddings(transformed_queries)
    all_chunks: list = []
    seen_chunk_keys: set = set()
    for query_embedding in query_embeddings:
        chunks = await _retrieve_chunks_for_documents(
            doc_ids=[doc_id],
            query_embedding=query_embedding,
            match_count=match_count,
        )
        for chunk in chunks:
            key = (chunk.document_id, chunk.chunk_index)
            if key not in seen_chunk_keys:
                seen_chunk_keys.add(key)
                all_chunks.append(chunk)
    matching_chunks = all_chunks
    context = build_context_from_chunks(matching_chunks, session_context=session_context)
    answer = await generate_answer(question, context)

    base: dict = {
        "question": question,
        "doc_id": doc_id,
        "chunks": len(matching_chunks),
        "answer": answer,
        "sources": _build_sources(matching_chunks),
    }
    llm_err = _structured_error_from_llm_answer(answer)
    if llm_err is not None:
        logger.warning("Chat LLM returned soft failure for document %s", doc_id)
        return {
            **base,
            "status": "error",
            "error": llm_err,
        }

    logger.info(f"Answer generated successfully for document {doc_id}")
    return {
        **base,
        "status": "ok",
    }


async def answer_questions_for_documents_batch(
    queries: list[dict],
    session_context: Optional[SessionContext] = None,
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

    transformed_query_lists = await asyncio.gather(
        *[transform_query(q["question"]) for q in normalized_queries]
    )
    flat_queries = [q for queries in transformed_query_lists for q in queries]
    flat_embeddings = await get_embeddings(flat_queries)
    if len(flat_embeddings) != len(flat_queries):
        mismatch_message = (
            f"Embedding mismatch: got {len(flat_embeddings)} embeddings for {len(flat_queries)} queries"
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

    per_query_embeddings: list[list[list[float]]] = []
    offset = 0
    for tq_list in transformed_query_lists:
        n = len(tq_list)
        per_query_embeddings.append(flat_embeddings[offset : offset + n])
        offset += n

    async def _process_query(
        query: dict, query_embeddings: list[list[float]]
    ) -> dict:
        try:
            all_chunks: list = []
            seen_chunk_keys: set = set()
            for query_embedding in query_embeddings:
                chunks = await _retrieve_chunks_for_documents(
                    doc_ids=query["doc_ids"],
                    query_embedding=query_embedding,
                    match_count=query["match_count"],
                )
                for chunk in chunks:
                    key = (chunk.document_id, chunk.chunk_index)
                    if key not in seen_chunk_keys:
                        seen_chunk_keys.add(key)
                        all_chunks.append(chunk)
            matching_chunks = all_chunks
            context = build_context_from_chunks(matching_chunks, session_context=session_context)
            answer = await generate_answer(query["question"], context)

            sources = _build_sources(matching_chunks)
            llm_err = _structured_error_from_llm_answer(answer)
            if llm_err is not None:
                return {
                    "status": "error",
                    "question": query["question"],
                    "doc_ids": query["doc_ids"],
                    "chunks": len(matching_chunks),
                    "answer": answer,
                    "sources": sources,
                    "error": llm_err,
                }

            return {
                "status": "ok",
                "question": query["question"],
                "doc_ids": query["doc_ids"],
                "chunks": len(matching_chunks),
                "answer": answer,
                "sources": sources,
            }
        except Exception:
            logger.exception(
                "Batch query failed (doc_ids=%s, question_len=%d)",
                query["doc_ids"],
                len(query["question"]),
            )
            return {
                "status": "error",
                "question": query["question"],
                "doc_ids": query["doc_ids"],
                "chunks": 0,
                "error": {
                    "code": "query_processing_failed",
                    "message": "An error occurred processing this query.",
                },
            }

    return await asyncio.gather(
        *[
            _process_query(query, embeddings)
            for query, embeddings in zip(normalized_queries, per_query_embeddings)
        ]
    )

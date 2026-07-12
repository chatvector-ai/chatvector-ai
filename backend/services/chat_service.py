import logging
import asyncio
import json
import time
from typing import Optional, AsyncGenerator

from core.auth import AuthContext, require_current_tenant
from core.config import config
from core.session import SessionContext
from db import find_similar_chunks
from services.context_service import build_context_from_chunks
from services.query_service import transform_query
from services.retrieval_service import (
    filter_doc_ids_for_tenant,
    parse_retrieval_scope,
    rerank_chunks_if_enabled,
    resolve_scoped_doc_ids,
)
from services.session_service import get_session
from services.tenant_registry import get_tenant_document_ids

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


async def generate_answer(question: str, context: str) -> tuple[str, int, str]:
    """
    Lazily import answer dependency to keep module import side-effect free.

    Returns (answer, latency_ms, model_name).
    """
    from services.answer_service import generate_answer as _generate_answer

    return await _generate_answer(question, context)

async def generate_answer_stream(question: str, context: str) -> AsyncGenerator[str, None]:
    """
    Lazily import answer stream dependency.
    """
    from services.answer_service import generate_answer_stream as _generate_answer_stream

    async for chunk in _generate_answer_stream(question, context):
        yield chunk


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


async def _resolve_retrieval_doc_ids(
    *,
    scope: str | None,
    requested_doc_ids: list[str],
    session_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> list[str]:
    """Apply retrieval scope rules and tenant isolation checks.

    Falls back to the database when the in-memory tenant registry is empty
    (e.g. after a server restart) so that tenant-scope retrieval continues
    to work correctly across process restarts.
    """
    retrieval_scope = parse_retrieval_scope(scope)

    session_doc_ids: list[str] = []
    if session_id:
        session = get_session(session_id, tenant_id)
        if session:
            session_doc_ids = list(session.document_ids)

    tenant_doc_ids = await get_tenant_document_ids(tenant_id)

    doc_ids = resolve_scoped_doc_ids(
        retrieval_scope,
        requested_doc_ids=requested_doc_ids,
        session_doc_ids=session_doc_ids,
        tenant_doc_ids=tenant_doc_ids,
    )
    doc_ids = filter_doc_ids_for_tenant(doc_ids, tenant_doc_ids, tenant_id)
    return doc_ids


async def _retrieve_chunks_for_documents(
    doc_ids: list[str],
    query_embedding: list[float],
    match_count: int,
    tenant_id: str,
    *,
    session_id: Optional[str] = None,
    query_text: Optional[str] = None,
) -> list:
    retrieval_semaphore = _get_retrieval_semaphore()

    async def _search_one_document(doc_id: str) -> list:
        async with retrieval_semaphore:
            return await find_similar_chunks(
                doc_id=doc_id,
                query_embedding=query_embedding,
                match_count=match_count,
                session_id=session_id,
                query_text=query_text,
                tenant_id=tenant_id,
            )

    per_document_chunks = await asyncio.gather(
        *[_search_one_document(doc_id) for doc_id in doc_ids]
    )

    merged_chunks = []
    for chunks in per_document_chunks:
        merged_chunks.extend(chunks)

    return merged_chunks


async def _finalize_retrieved_chunks(question: str, chunks: list, match_count: int) -> list:
    """Apply optional reranking before context assembly."""
    return await rerank_chunks_if_enabled(question, chunks, top_k=match_count)


def _build_sources(chunks: list) -> list[dict]:
    """Extract citation metadata from retrieved chunks."""
    sources: list[dict] = []
    for chunk in chunks:
        source = {
            "file_name": chunk.file_name,
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
            "score": chunk.similarity,
        }
        if chunk.score_type is not None:
            source["score_type"] = chunk.score_type
        sources.append(source)
    return sources


def _is_compare_style_batch_query(doc_ids: list[str]) -> bool:
    """Single-document batch items are compare-style and isolate from session history."""
    return len(doc_ids) == 1


def _format_sse_event(event: str, data: dict | str) -> str:
    payload = json.dumps(data) if isinstance(data, dict) else data
    return f"event: {event}\ndata: {payload}\n\n"


def _build_stream_complete_payload(
    *,
    session_id: Optional[str],
    sources: list[dict],
    latency_ms: int,
    model: str,
) -> dict:
    return {
        "type": "complete",
        "session_id": session_id,
        "sources": sources,
        "latency_ms": latency_ms,
        "model": model,
    }


def _build_stream_error_payload(*, code: str, message: str) -> dict:
    return {
        "type": "error",
        "code": code,
        "message": message,
    }


async def answer_question_for_document(
    question: str,
    doc_id: str,
    match_count: int = 5,
    *,
    auth: AuthContext,
    session_id: Optional[str] = None,
    session_context: Optional[SessionContext] = None,
    scope: Optional[str] = None,
) -> dict:
    """
    Orchestrate the chat flow for a single question/document pair.
    """
    logger.info(f"Starting chat for document {doc_id} (session={session_id}, scope={scope or 'session'})")
    tenant_id = require_current_tenant(auth)

    doc_ids = await _resolve_retrieval_doc_ids(
        scope=scope,
        requested_doc_ids=[doc_id],
        session_id=session_id,
        tenant_id=tenant_id,
    )
    if not doc_ids:
        return {
            "question": question,
            "doc_id": doc_id,
            "chunks": 0,
            "answer": "",
            "sources": [],
            "latency_ms": 0,
            "model": "",
            "status": "error",
            "error": {
                "code": "no_documents_in_scope",
                "message": "No documents available for retrieval in the requested scope.",
            },
        }

    # Load session history before query transformation so follow-up questions
    # can be resolved into standalone retrieval queries.
    history: list[dict] = []
    if session_id:
        import db
        try:
            history = await db.get_session_history(
                session_id=session_id, limit=config.MAX_SESSION_HISTORY_MESSAGES, tenant_id=tenant_id
            )
        except Exception as e:
            logger.error(f"Failed to load chat history for session {session_id}: {e}", exc_info=True)

    transformation_history = (
        history[: config.QUERY_TRANSFORMATION_HISTORY_WINDOW] if history else None
    )
    transformed_queries = await transform_query(question, history=transformation_history)
    query_embeddings = await get_embeddings(transformed_queries)
    all_chunks: list = []
    seen_chunk_keys: set = set()
    for query_embedding in query_embeddings:
        chunks = await _retrieve_chunks_for_documents(
            doc_ids=doc_ids,
            query_embedding=query_embedding,
            match_count=match_count,
            tenant_id=tenant_id,
            session_id=session_id,
            query_text=question,
        )
        for chunk in chunks:
            key = (chunk.document_id, chunk.chunk_index)
            if key not in seen_chunk_keys:
                seen_chunk_keys.add(key)
                all_chunks.append(chunk)
    matching_chunks = await _finalize_retrieved_chunks(question, all_chunks, match_count)

    if history:
        if not session_context:
            session_context = SessionContext()
        session_context.chat_history = history

    context = build_context_from_chunks(matching_chunks, session_context=session_context)
    answer, latency_ms, model_name = await generate_answer(question, context)
    base: dict = {
        "question": question,
        "doc_id": doc_id,
        "chunks": len(matching_chunks),
        "answer": answer,
        "sources": _build_sources(matching_chunks),
        "latency_ms": latency_ms,
        "model": model_name,
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

    if session_id:
        try:
            import db
            await db.store_chat_message(
                session_id=session_id, role="user", content=question, tenant_id=tenant_id
            )
            await db.store_chat_message(
                session_id=session_id, role="assistant", content=answer, tenant_id=tenant_id
            )
        except Exception as e:
            logger.error(f"Failed to store chat messages for session {session_id}: {e}", exc_info=True)

    return {
        **base,
        "status": "ok",
    }


async def answer_question_stream_for_document(
    question: str,
    doc_id: str,
    match_count: int = 5,
    *,
    auth: AuthContext,
    session_id: Optional[str] = None,
    session_context: Optional[SessionContext] = None,
    scope: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Orchestrate the chat flow for a single question/document pair, yielding
    a server-sent events (SSE) stream.
    """
    logger.info(f"Starting chat stream for document {doc_id} (scope={scope or 'session'})")
    tenant_id = require_current_tenant(auth)

    try:
        doc_ids = await _resolve_retrieval_doc_ids(
            scope=scope,
            requested_doc_ids=[doc_id],
            session_id=session_id,
            tenant_id=tenant_id,
        )
        if not doc_ids:
            yield _format_sse_event(
                "error",
                _build_stream_error_payload(
                    code="no_documents_in_scope",
                    message="No documents available for retrieval in the requested scope.",
                ),
            )
            return

        # Load session history before query transformation so follow-up questions
        # can be resolved into standalone retrieval queries.
        history: list[dict] = []
        if session_id:
            import db
            try:
                history = await db.get_session_history(
                    session_id=session_id, limit=config.MAX_SESSION_HISTORY_MESSAGES, tenant_id=tenant_id
                )
            except Exception as e:
                logger.error(f"Failed to load chat history for session {session_id}: {e}", exc_info=True)

        transformation_history = (
            history[: config.QUERY_TRANSFORMATION_HISTORY_WINDOW] if history else None
        )
        transformed_queries = await transform_query(question, history=transformation_history)
        query_embeddings = await get_embeddings(transformed_queries)
        all_chunks: list = []
        seen_chunk_keys: set = set()
        for query_embedding in query_embeddings:
            chunks = await _retrieve_chunks_for_documents(
                doc_ids=doc_ids,
                query_embedding=query_embedding,
                match_count=match_count,
                tenant_id=tenant_id,
                query_text=question,
            )
            for chunk in chunks:
                key = (chunk.document_id, chunk.chunk_index)
                if key not in seen_chunk_keys:
                    seen_chunk_keys.add(key)
                    all_chunks.append(chunk)
        matching_chunks = await _finalize_retrieved_chunks(question, all_chunks, match_count)
        sources = _build_sources(matching_chunks)

        if history:
            if not session_context:
                session_context = SessionContext()
            session_context.chat_history = history

        context = build_context_from_chunks(matching_chunks, session_context=session_context)

        full_answer_chunks: list[str] = []
        t0 = time.perf_counter()
        try:
            async for chunk in generate_answer_stream(question, context):
                err = _structured_error_from_llm_answer(chunk)
                if err is not None:
                    yield _format_sse_event(
                        "error",
                        _build_stream_error_payload(
                            code=err["code"],
                            message=err["message"],
                        ),
                    )
                    return
                full_answer_chunks.append(chunk)
                yield f"event: token\ndata: {json.dumps(chunk)}\n\n"
        except asyncio.CancelledError:
            logger.info(
                "Chat stream cancelled for document %s (session=%s)",
                doc_id,
                session_id,
            )
            raise

        latency_ms = int((time.perf_counter() - t0) * 1000)
        from services.providers import get_llm_provider

        model_name = getattr(get_llm_provider(), "model_name", "")

        yield _format_sse_event(
            "complete",
            _build_stream_complete_payload(
                session_id=session_id,
                sources=sources,
                latency_ms=latency_ms,
                model=model_name,
            ),
        )
        # Legacy completion marker — deprecated; retained for backward compatibility.
        yield "event: done\ndata: [DONE]\n\n"
        logger.info(f"Answer stream generated successfully for document {doc_id}")

        if session_id:
            try:
                import db
                full_answer = "".join(full_answer_chunks)
                await db.store_chat_message(
                    session_id=session_id, role="user", content=question, tenant_id=tenant_id
                )
                await db.store_chat_message(
                    session_id=session_id, role="assistant", content=full_answer, tenant_id=tenant_id
                )
            except Exception as e:
                logger.error(f"Failed to store streaming chat messages for session {session_id}: {e}", exc_info=True)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Stream failed for document {doc_id}: {e}", exc_info=True)
        yield _format_sse_event(
            "error",
            _build_stream_error_payload(
                code="stream_failed",
                message="An unexpected error occurred.",
            ),
        )

async def answer_questions_for_documents_batch(
    queries: list[dict],
    *,
    auth: AuthContext,
    session_context: Optional[SessionContext] = None,
    scope: Optional[str] = None,
) -> list[dict]:
    """
    Process multiple question/document retrieval requests in one call.

    Note: The `session_context` provided is shared across all queries in the batch.
    It is assumed that a batch does not mix queries from different sessions.
    """
    if not queries:
        return []

    tenant_id = require_current_tenant(auth)

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
                "session_id": query.get("session_id"),
                "scope": query.get("scope", scope),
            }
        )

    # Pre-load session histories so each query's transformation can resolve
    # follow-up references.  One DB round-trip per unique session_id.
    async def _load_batch_history(session_id: str | None) -> list[dict]:
        if not session_id:
            return []
        import db
        try:
            return await db.get_session_history(
                session_id=session_id,
                limit=config.MAX_SESSION_HISTORY_MESSAGES,
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to pre-load session history for batch transformation (session=%s): %s",
                session_id,
                e,
                exc_info=True,
            )
            return []

    per_query_histories: list[list[dict]] = list(
        await asyncio.gather(
            *[_load_batch_history(q.get("session_id")) for q in normalized_queries]
        )
    )

    transformed_query_lists = await asyncio.gather(
        *[
            transform_query(
                q["question"],
                history=(
                    h[: config.QUERY_TRANSFORMATION_HISTORY_WINDOW] if h else None
                ),
            )
            for q, h in zip(normalized_queries, per_query_histories)
        ]
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
        query: dict, query_embeddings: list[list[float]], preloaded_history: list[dict]
    ) -> dict:
        try:
            session_id = query.get("session_id")
            query_scope = query.get("scope")
            doc_ids = await _resolve_retrieval_doc_ids(
                scope=query_scope,
                requested_doc_ids=query["doc_ids"],
                session_id=session_id,
                tenant_id=tenant_id,
            )
            if not doc_ids:
                return {
                    "status": "error",
                    "question": query["question"],
                    "doc_ids": query["doc_ids"],
                    "chunks": 0,
                    "error": {
                        "code": "no_documents_in_scope",
                        "message": "No documents available for retrieval in the requested scope.",
                    },
                    "latency_ms": 0,
                    "model": "",
                    "session_id": session_id,
                }

            all_chunks: list = []
            seen_chunk_keys: set = set()
            for query_embedding in query_embeddings:
                chunks = await _retrieve_chunks_for_documents(
                    doc_ids=doc_ids,
                    query_embedding=query_embedding,
                    match_count=query["match_count"],
                    tenant_id=tenant_id,
                    session_id=session_id,
                    query_text=query["question"],
                )
                for chunk in chunks:
                    key = (chunk.document_id, chunk.chunk_index)
                    if key not in seen_chunk_keys:
                        seen_chunk_keys.add(key)
                        all_chunks.append(chunk)
            matching_chunks = await _finalize_retrieved_chunks(
                query["question"], all_chunks, query["match_count"]
            )

            is_compare_style = _is_compare_style_batch_query(query["doc_ids"])
            query_session_context = session_context
            if preloaded_history and not is_compare_style:
                from copy import deepcopy
                query_session_context = deepcopy(session_context) if session_context else SessionContext()
                query_session_context.chat_history = preloaded_history

            context = build_context_from_chunks(matching_chunks, session_context=query_session_context)
            answer, latency_ms, model_name = await generate_answer(query["question"], context)

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
                    "latency_ms": latency_ms,
                    "model": model_name,
                    "session_id": session_id,
                }

            if session_id and not is_compare_style:
                try:
                    import db
                    await db.store_chat_message(
                        session_id=session_id, role="user", content=query["question"], tenant_id=tenant_id
                    )
                    await db.store_chat_message(
                        session_id=session_id, role="assistant", content=answer, tenant_id=tenant_id
                    )
                except Exception as e:
                    logger.error(f"Failed to store batch chat messages for session {session_id}: {e}", exc_info=True)

            return {
                "status": "ok",
                "question": query["question"],
                "doc_ids": query["doc_ids"],
                "chunks": len(matching_chunks),
                "answer": answer,
                "sources": sources,
                "latency_ms": latency_ms,
                "model": model_name,
                "session_id": session_id,
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
            _process_query(query, embeddings, history)
            for query, embeddings, history in zip(
                normalized_queries, per_query_embeddings, per_query_histories
            )
        ]
    )

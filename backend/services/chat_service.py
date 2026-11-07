import logging
import asyncio
import json
import time
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, AsyncGenerator, cast

from core.auth import AuthContext, require_current_tenant
from core.config import config
from core.session import SessionContext
from db import filter_document_ids_by_metadata, find_similar_chunks
from services.context_service import build_context_from_chunks
from services.history_config import history_load_limit, prepare_turn_history
from services.query_service import QueryTransformResult, transform_query
from services.retrieval_config import (
    EffectiveRetrievalConfig,
    InvalidRetrievalConfigError,
    resolve_retrieval_config,
    transformation_is_request_scoped,
)
from services.retrieval_presets import (
    RetrievalPresetNotFoundError,
    extract_preset_name,
    lookup_retrieval_preset,
)
from services.retrieval_service import (
    filter_doc_ids_for_tenant,
    parse_retrieval_scope,
    rerank_chunks_with_debug,
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
_batch_llm_limit = max(1, int(config.CHAT_BATCH_LLM_CONCURRENCY))
# Shared per API process; concurrent /chat/batch requests use the same cap.
_batch_llm_semaphore = asyncio.Semaphore(_batch_llm_limit)


def _get_retrieval_semaphore() -> asyncio.Semaphore:
    global _retrieval_limit, _retrieval_semaphore

    configured_limit = max(1, int(config.RETRIEVAL_MAX_CONCURRENCY))
    if configured_limit != _retrieval_limit:
        _retrieval_limit = configured_limit
        _retrieval_semaphore = asyncio.Semaphore(_retrieval_limit)

    return _retrieval_semaphore


def _get_batch_llm_semaphore() -> asyncio.Semaphore:
    global _batch_llm_limit, _batch_llm_semaphore

    configured_limit = max(1, int(config.CHAT_BATCH_LLM_CONCURRENCY))
    if configured_limit != _batch_llm_limit:
        _batch_llm_limit = configured_limit
        _batch_llm_semaphore = asyncio.Semaphore(_batch_llm_limit)

    return _batch_llm_semaphore


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


async def get_embeddings(
    texts: list[str],
    *,
    tenant_id: str | None = None,
    use_cache: bool | None = None,
) -> list[list[float]]:
    """
    Lazily import batch embedding dependency to keep module import side-effect free.

    ``use_cache`` is forwarded to the embedding layer so callers such as eval
    can bypass the cache without a separate retrieval path.
    """
    from services.embedding_service import get_embeddings as _get_embeddings

    return await _get_embeddings(texts, tenant_id=tenant_id, use_cache=use_cache)


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
    metadata_filter: Mapping[str, Any] | None = None,
) -> list[str]:
    """Apply retrieval scope rules, tenant isolation checks, and metadata filter.

    Falls back to the database when the in-memory tenant registry is empty
    (e.g. after a server restart) so that tenant-scope retrieval continues
    to work correctly across process restarts.
    """
    retrieval_scope = parse_retrieval_scope(scope)

    session_doc_ids: list[str] = []
    if session_id:
        session = await get_session(session_id, tenant_id)
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
    if metadata_filter and doc_ids:
        # Document-level filter over the already tenant-scoped candidates.
        doc_ids = await filter_document_ids_by_metadata(
            tenant_id=tenant_id,
            doc_ids=doc_ids,
            metadata_filter=dict(metadata_filter),
        )
    return doc_ids


def _scope_error(
    doc_ids: list[str],
    *,
    requested_doc_ids: list[str],
    effective: EffectiveRetrievalConfig,
) -> dict | None:
    """Structured error when a chat request has no usable scope, else ``None``.

    With a ``metadata_filter`` at least one requested/anchor document must
    remain in the filtered scope set; the filter never replaces the anchors.
    """
    if effective.metadata_filter and not any(doc_id in doc_ids for doc_id in requested_doc_ids):
        return {
            "code": "anchor_document_excluded_by_filter",
            "message": "The requested document is not in the retrieval scope after applying metadata_filter.",
        }
    if not doc_ids:
        return {
            "code": "no_documents_in_scope",
            "message": "No documents available for retrieval in the requested scope.",
        }
    return None


async def _retrieve_chunks_for_documents(
    doc_ids: list[str],
    query_embedding: list[float],
    match_count: int,
    tenant_id: str,
    *,
    session_id: Optional[str] = None,
    query_text: Optional[str] = None,
    hybrid_enabled: Optional[bool] = None,
) -> list:
    retrieval_semaphore = _get_retrieval_semaphore()

    async def _search_one_document(doc_id: str) -> list:
        async with retrieval_semaphore:
            search_kwargs = {
                "doc_id": doc_id,
                "query_embedding": query_embedding,
                "match_count": match_count,
                "session_id": session_id,
                "query_text": query_text,
                "tenant_id": tenant_id,
            }
            if hybrid_enabled is not None:
                search_kwargs["hybrid_enabled"] = hybrid_enabled
            return await find_similar_chunks(**search_kwargs)

    per_document_chunks = await asyncio.gather(
        *[_search_one_document(doc_id) for doc_id in doc_ids]
    )

    merged_chunks = []
    for chunks in per_document_chunks:
        merged_chunks.extend(chunks)

    return merged_chunks


def _chunk_global_order_key(chunk) -> tuple:
    """Sort key: higher effective score first, then document_id, then chunk_index.

    ``ChunkMatch.similarity`` is the comparable score for the current mode
    (cosine in vector mode, within-document RRF in hybrid). Missing similarity
    sorts last. Ties do not preserve request order.
    """
    similarity = getattr(chunk, "similarity", None)
    document_id = getattr(chunk, "document_id", None)
    chunk_index = getattr(chunk, "chunk_index", None)
    return (
        similarity is None,
        0.0 if similarity is None else -float(similarity),
        document_id is None,
        "" if document_id is None else str(document_id),
        chunk_index is None,
        -1 if chunk_index is None else chunk_index,
    )


def _order_chunks_by_effective_score(chunks: list) -> list:
    return sorted(chunks, key=_chunk_global_order_key)


async def _finalize_retrieved_chunks(
    question: str,
    chunks: list,
    match_count: int,
    *,
    reranking_enabled: bool | None = None,
    reranker_provider: str | None = None,
) -> tuple[list, dict | None]:
    """Apply optional reranking before context assembly.

    Returns the chunks and the reranker debug block (``None`` when reranking did not run).
    """
    return await rerank_chunks_with_debug(
        question,
        chunks,
        top_k=match_count,
        reranking_enabled=reranking_enabled,
        reranker_provider=reranker_provider,
    )


@dataclass
class RetrievalResult:
    """Candidates and query text from one retrieval, without answer generation."""

    chunks: list
    queries: list[str]
    primary_query: str
    context: str
    timing_ms: dict[str, int]
    transform_result: QueryTransformResult
    effective_config: EffectiveRetrievalConfig
    reranker_debug: dict | None = None

    def to_debug_dict(self) -> dict:
        payload = self.transform_result.to_retrieval_debug()
        payload["effective_config"] = self.effective_config.to_debug_dict()
        payload["resolved_preset"] = self.effective_config.resolved_preset
        if self.reranker_debug is not None:
            payload["reranker"] = dict(self.reranker_debug)
        payload["effective_retrieval_query"] = self.primary_query
        payload["timing_ms"] = dict(self.timing_ms)
        return payload


def resolve_effective_retrieval(
    *,
    match_count: int,
    scope: str | None,
    retrieval_fields: dict | None,
) -> EffectiveRetrievalConfig:
    if retrieval_fields is None:
        fields: dict = {"match_count": match_count}
        if scope is not None:
            fields["scope"] = scope
    else:
        fields = retrieval_fields
    preset_name = extract_preset_name(fields)
    preset_fields = lookup_retrieval_preset(preset_name) if preset_name else None
    return resolve_retrieval_config(
        fields,
        preset_fields=preset_fields,
        resolved_preset=preset_name,
    )


def _apply_compare_history_policy(
    effective: EffectiveRetrievalConfig,
    *,
    compare_style: bool,
) -> EffectiveRetrievalConfig:
    """Single-document batch items skip history during transform unless overridden."""
    if compare_style and effective.sources.get("skip_history_transform") not in {
        "request",
        "preset",
    }:
        return replace(effective, skip_history_transform=True)
    return effective


def _rerank_overrides(effective: EffectiveRetrievalConfig) -> dict:
    overrides: dict = {}
    request_scoped = {"request", "preset"}
    if effective.sources.get("reranking_enabled") in request_scoped:
        overrides["reranking_enabled"] = effective.reranking_enabled
    if effective.sources.get("reranker_provider") in request_scoped:
        overrides["reranker_provider"] = effective.reranker_provider
        overrides.setdefault("reranking_enabled", effective.reranking_enabled)
    return overrides


async def retrieve_for_documents(
    query: str,
    document_ids: list[str],
    tenant_id: str,
    effective_retrieval_config: EffectiveRetrievalConfig,
    *,
    session_id: str | None = None,
    history_for_transform: list[dict] | None = None,
    skip_history_transform: bool | None = None,
    session_context: SessionContext | None = None,
    use_embedding_cache: bool | None = None,
    max_context_chars: int | None = None,
    transform_result: QueryTransformResult | None = None,
    query_embeddings: list[list[float]] | None = None,
    resolution_policy=None,
    history_observation=None,
) -> RetrievalResult:
    """Run retrieval for one query. Does not call answer generation.

    Vector search uses every transformed query. Keyword search and reranking
    use the primary retrieval query: the first entry in that list.
    """
    started = time.perf_counter()
    skip_history = (
        effective_retrieval_config.skip_history_transform
        if skip_history_transform is None
        else skip_history_transform
    )
    history_arg = None if skip_history else history_for_transform

    transform_started = time.perf_counter()
    if transform_result is None:
        transform_kwargs = {}
        if transformation_is_request_scoped(effective_retrieval_config):
            transform_kwargs["effective_config"] = effective_retrieval_config
        transform_result = await transform_query(
            query,
            history=history_arg,
            resolution_policy=resolution_policy,
            history_observation=history_observation,
            **transform_kwargs,
        )
    transform_ms = int((time.perf_counter() - transform_started) * 1000)

    queries = list(transform_result.queries) or [query]
    primary_query = queries[0]

    embed_started = time.perf_counter()
    if query_embeddings is None:
        embed_kwargs: dict = {"tenant_id": tenant_id}
        if use_embedding_cache is not None:
            embed_kwargs["use_cache"] = use_embedding_cache
        query_embeddings = await get_embeddings(queries, **embed_kwargs)
    embed_ms = int((time.perf_counter() - embed_started) * 1000)
    if len(query_embeddings) != len(queries):
        mismatch = RuntimeError(
            f"Embedding mismatch: got {len(query_embeddings)} embeddings for {len(queries)} queries"
        )
        mismatch.code = "embedding_mismatch"  # type: ignore[attr-defined]
        raise mismatch

    hybrid_enabled = (
        effective_retrieval_config.hybrid_enabled
        if effective_retrieval_config.sources.get("hybrid_enabled") in {"request", "preset"}
        else None
    )
    search_started = time.perf_counter()
    all_chunks: list = []
    seen_chunk_keys: set = set()
    for query_embedding in query_embeddings:
        chunks = await _retrieve_chunks_for_documents(
            doc_ids=document_ids,
            query_embedding=query_embedding,
            match_count=effective_retrieval_config.match_count,
            tenant_id=tenant_id,
            session_id=session_id,
            query_text=primary_query,
            hybrid_enabled=hybrid_enabled,
        )
        for chunk in chunks:
            key = (getattr(chunk, "document_id", None), getattr(chunk, "chunk_index", None))
            if key not in seen_chunk_keys:
                seen_chunk_keys.add(key)
                all_chunks.append(chunk)
    search_ms = int((time.perf_counter() - search_started) * 1000)

    if config.ENABLE_GRAPH_RETRIEVAL:
        from services.graph_retrieval import expand_chunks_if_enabled

        all_chunks = expand_chunks_if_enabled(
            all_chunks,
            allowed_document_ids=document_ids,
        )

    all_chunks = _order_chunks_by_effective_score(all_chunks)

    rerank_started = time.perf_counter()
    matching_chunks, reranker_debug = await _finalize_retrieved_chunks(
        primary_query,
        all_chunks,
        effective_retrieval_config.match_count,
        **_rerank_overrides(effective_retrieval_config),
    )
    rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
    if reranker_debug is None:
        matching_chunks = matching_chunks[: effective_retrieval_config.match_count]

    context_started = time.perf_counter()
    context_kwargs = {}
    if max_context_chars is not None:
        context_kwargs["max_chars"] = max_context_chars
    context = build_context_from_chunks(
        matching_chunks,
        session_context=session_context,
        **context_kwargs,
    )
    context_ms = int((time.perf_counter() - context_started) * 1000)

    return RetrievalResult(
        chunks=matching_chunks,
        queries=queries,
        primary_query=primary_query,
        context=context,
        timing_ms={
            "transform": transform_ms,
            "embed": embed_ms,
            "search": search_ms,
            "rerank": rerank_ms,
            "context": context_ms,
            "total": int((time.perf_counter() - started) * 1000),
        },
        transform_result=transform_result,
        effective_config=effective_retrieval_config,
        reranker_debug=reranker_debug,
    )


_COMPONENT_SCORE_FIELDS = (
    "vector_score",
    "full_text_score",
    "rrf_score",
    "reranker_score",
    "rerank_order",
)


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
        for field in _COMPONENT_SCORE_FIELDS:
            value = getattr(chunk, field, None)
            if value is not None:
                source[field] = value
        sources.append(source)
    return sources


def _build_source_snapshot(
    chunks: list, sources: list[dict] | None = None
) -> list[dict]:
    """Copy display and provenance fields stored on the assistant message.

    Live ``_build_sources`` omits ``document_id``. The stored copy includes it
    so a later reader can render the citation without looking the document up.
    Pass the already-built live ``sources`` so display fields cannot drift and
    ``_build_sources`` is not run twice.
    """
    live_sources = sources if sources is not None else _build_sources(chunks)
    snapshot: list[dict] = []
    for chunk, source in zip(chunks, live_sources):
        item = dict(source)
        document_id = getattr(chunk, "document_id", None)
        if document_id is not None:
            item["document_id"] = str(document_id)
        snapshot.append(item)
    return snapshot


def _is_compare_style_batch_query(doc_ids: list[str]) -> bool:
    """Single-document batch items are compare-style and isolate from session history."""
    return len(doc_ids) == 1


def validate_and_normalize_batch_queries(queries: list[dict]) -> list[dict]:
    """Validate batch structure using runtime config. Raises ValueError on failure."""
    if not queries:
        return []

    if len(queries) > config.CHAT_BATCH_MAX_ITEMS:
        raise ValueError(
            f"Batch size {len(queries)} exceeds CHAT_BATCH_MAX_ITEMS={config.CHAT_BATCH_MAX_ITEMS}"
        )

    normalized_queries: list[dict] = []
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

        normalized = {
            "question": question,
            "doc_ids": doc_ids,
            "match_count": match_count,
            "session_id": query.get("session_id"),
            "scope": query.get("scope"),
        }
        if "retrieval_fields" in query:
            normalized["retrieval_fields"] = query.get("retrieval_fields") or {}
        if "history_fields" in query:
            normalized["history_fields"] = query.get("history_fields") or {}
        normalized_queries.append(normalized)

    return normalized_queries


def merge_batch_results(
    slot_results: list[dict | None],
    service_indices: list[int],
    service_results: list[dict],
) -> list[dict]:
    """Merge per-item setup failures with batch service results in request order."""
    merged: list[dict | None] = [None] * len(slot_results)
    for orig_idx, result in zip(service_indices, service_results):
        merged[orig_idx] = result
    for index, slot in enumerate(slot_results):
        if slot is not None:
            merged[index] = slot
    return cast(list[dict], merged)


async def prepare_batch_chat_items(
    raw_queries: list[dict],
    *,
    tenant_id: str,
    batch_session_id: str | None,
) -> tuple[list[tuple[int, dict]], list[dict | None]]:
    """Validate batch items and perform per-item ownership/session setup.

    Returns ``(service_items, slot_results)`` where ``service_items`` are
    ``(original_index, normalized_query)`` pairs ready for the batch service,
    and ``slot_results[i]`` is either ``None`` (proceed) or a structured error.
    """
    import db
    from services.session_service import get_or_create_session, register_session_document
    from services.tenant_registry import register_tenant_document

    normalized = validate_and_normalize_batch_queries(raw_queries)
    slot_results: list[dict | None] = [None] * len(normalized)
    service_items: list[tuple[int, dict]] = []

    for index, query in enumerate(normalized):
        missing_doc_ids: list[str] = []
        for doc_id in query["doc_ids"]:
            doc = await db.get_document(doc_id, tenant_id=tenant_id)
            if doc is None:
                missing_doc_ids.append(doc_id)

        if missing_doc_ids:
            slot_results[index] = {
                "status": "error",
                "question": query["question"],
                "doc_ids": query["doc_ids"],
                "chunks": 0,
                "error": {
                    "code": "document_not_found",
                    "message": "One or more documents were not found.",
                },
                "latency_ms": 0,
                "model": "",
                "session_id": query.get("session_id") or batch_session_id,
            }
            continue

        session = await get_or_create_session(
            session_id=query.get("session_id") or batch_session_id,
            tenant_id=tenant_id,
        )
        prepared = dict(query)
        prepared["session_id"] = session.id
        for doc_id in query["doc_ids"]:
            await register_session_document(session.id, doc_id, tenant_id)
            register_tenant_document(tenant_id, doc_id)
        service_items.append((index, prepared))

    return service_items, slot_results


def _format_sse_event(event: str, data: dict | str) -> str:
    payload = json.dumps(data) if isinstance(data, dict) else data
    return f"event: {event}\ndata: {payload}\n\n"


def _build_stream_complete_payload(
    *,
    session_id: Optional[str],
    sources: list[dict],
    latency_ms: int,
    model: str,
    retrieval_debug: dict | None = None,
    request_latency_ms: int | None = None,
    message_id: str | None = None,
) -> dict:
    payload = {
        "type": "complete",
        "session_id": session_id,
        "sources": sources,
        "latency_ms": latency_ms,
        "model": model,
    }
    if request_latency_ms is not None:
        payload["request_latency_ms"] = request_latency_ms
    if retrieval_debug is not None:
        payload["retrieval_debug"] = retrieval_debug
    # Present only after the assistant row is stored. Omitted otherwise.
    if message_id:
        payload["message_id"] = message_id
    return payload


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
    debug_retrieval: bool = False,
    retrieval_fields: dict | None = None,
    history_fields: dict | None = None,
) -> dict:
    """
    Orchestrate the chat flow for a single question/document pair.
    """
    logger.info(f"Starting chat for document {doc_id} (session={session_id}, scope={scope or 'session'})")
    tenant_id = require_current_tenant(auth)
    effective = resolve_effective_retrieval(
        match_count=match_count,
        scope=scope,
        retrieval_fields=retrieval_fields,
    )

    doc_ids = await _resolve_retrieval_doc_ids(
        scope=effective.scope,
        requested_doc_ids=[doc_id],
        session_id=session_id,
        tenant_id=tenant_id,
        metadata_filter=effective.metadata_filter,
    )
    scope_error = _scope_error(doc_ids, requested_doc_ids=[doc_id], effective=effective)
    if scope_error is not None:
        return {
            "question": question,
            "doc_id": doc_id,
            "chunks": 0,
            "answer": "",
            "sources": [],
            "latency_ms": 0,
            "model": "",
            "status": "error",
            "session_id": session_id,
            "error": scope_error,
        }

    # Load session history before query transformation so follow-up questions
    # can be resolved into standalone retrieval queries.
    history: list[dict] = []
    if session_id:
        import db
        try:
            history = await db.get_session_history(
                session_id=session_id,
                limit=history_load_limit(history_fields),
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.error(f"Failed to load chat history for session {session_id}: {e}", exc_info=True)

    plan = prepare_turn_history(
        history,
        history_fields,
        skip_history_transform=effective.skip_history_transform,
        apply_generation_history=True,
        global_query_transformation_enabled=bool(config.QUERY_TRANSFORMATION_ENABLED),
    )
    if history:
        if not session_context:
            session_context = SessionContext()
        session_context.chat_history = plan.generation_history

    retrieval = await retrieve_for_documents(
        question,
        doc_ids,
        tenant_id,
        effective,
        session_id=session_id,
        history_for_transform=plan.transform_history,
        session_context=session_context,
        resolution_policy=plan.policy,
        history_observation=plan.observation,
    )
    matching_chunks = retrieval.chunks
    context = retrieval.context
    retrieval_debug = retrieval.to_debug_dict() if debug_retrieval else None
    answer, latency_ms, model_name = await generate_answer(question, context)
    sources = _build_sources(matching_chunks)
    base: dict = {
        "question": question,
        "doc_id": doc_id,
        "chunks": len(matching_chunks),
        "answer": answer,
        "sources": sources,
        "latency_ms": latency_ms,
        "model": model_name,
        "session_id": session_id,
    }
    llm_err = _structured_error_from_llm_answer(answer)
    if llm_err is not None:
        logger.warning("Chat LLM returned soft failure for document %s", doc_id)
        error_response = {
            **base,
            "status": "error",
            "error": llm_err,
        }
        if retrieval_debug is not None:
            error_response["retrieval_debug"] = retrieval_debug
        return error_response

    logger.info(f"Answer generated successfully for document {doc_id}")

    if session_id:
        try:
            import db
            await db.store_chat_turn(
                session_id=session_id,
                question=question,
                answer=answer,
                tenant_id=tenant_id,
                sources=_build_source_snapshot(matching_chunks, sources),
            )
        except Exception as e:
            logger.error(f"Failed to store chat turn for session {session_id}: {e}", exc_info=True)

    response = {
        **base,
        "status": "ok",
    }
    if retrieval_debug is not None:
        response["retrieval_debug"] = retrieval_debug
    return response


async def answer_question_stream_for_document(
    question: str,
    doc_id: str,
    match_count: int = 5,
    *,
    auth: AuthContext,
    session_id: Optional[str] = None,
    session_context: Optional[SessionContext] = None,
    scope: Optional[str] = None,
    debug_retrieval: bool = False,
    retrieval_fields: dict | None = None,
    history_fields: dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    Orchestrate the chat flow for a single question/document pair, yielding
    a server-sent events (SSE) stream.
    """
    logger.info(f"Starting chat stream for document {doc_id} (scope={scope or 'session'})")
    request_started = time.perf_counter()
    tenant_id = require_current_tenant(auth)

    try:
        effective = resolve_effective_retrieval(
            match_count=match_count,
            scope=scope,
            retrieval_fields=retrieval_fields,
        )
        doc_ids = await _resolve_retrieval_doc_ids(
            scope=effective.scope,
            requested_doc_ids=[doc_id],
            session_id=session_id,
            tenant_id=tenant_id,
            metadata_filter=effective.metadata_filter,
        )
        scope_error = _scope_error(doc_ids, requested_doc_ids=[doc_id], effective=effective)
        if scope_error is not None:
            yield _format_sse_event(
                "error",
                _build_stream_error_payload(
                    code=scope_error["code"],
                    message=scope_error["message"],
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
                    session_id=session_id,
                    limit=history_load_limit(history_fields),
                    tenant_id=tenant_id,
                )
            except Exception as e:
                logger.error(f"Failed to load chat history for session {session_id}: {e}", exc_info=True)

        plan = prepare_turn_history(
            history,
            history_fields,
            skip_history_transform=effective.skip_history_transform,
            apply_generation_history=True,
            global_query_transformation_enabled=bool(config.QUERY_TRANSFORMATION_ENABLED),
        )
        if history:
            if not session_context:
                session_context = SessionContext()
            session_context.chat_history = plan.generation_history

        retrieval = await retrieve_for_documents(
            question,
            doc_ids,
            tenant_id,
            effective,
            session_id=session_id,
            history_for_transform=plan.transform_history,
            session_context=session_context,
            resolution_policy=plan.policy,
            history_observation=plan.observation,
        )
        matching_chunks = retrieval.chunks
        sources = _build_sources(matching_chunks)
        context = retrieval.context
        retrieval_debug = retrieval.to_debug_dict() if debug_retrieval else None

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
        request_latency_ms = int((time.perf_counter() - request_started) * 1000)
        from services.providers import get_llm_provider

        model_name = getattr(get_llm_provider(), "model_name", "")

        full_answer = "".join(full_answer_chunks)
        if not full_answer.strip():
            full_answer = "No response."

        assistant_message_id: str | None = None
        if session_id:
            try:
                import db
                _user_message_id, raw_assistant_id = await db.store_chat_turn(
                    session_id=session_id,
                    question=question,
                    answer=full_answer,
                    tenant_id=tenant_id,
                    sources=_build_source_snapshot(matching_chunks, sources),
                )
                if isinstance(raw_assistant_id, str) and raw_assistant_id:
                    assistant_message_id = raw_assistant_id
            except Exception as e:
                logger.error(
                    f"Failed to store streaming chat turn for session {session_id}: {e}",
                    exc_info=True,
                )

        yield _format_sse_event(
            "complete",
            _build_stream_complete_payload(
                session_id=session_id,
                sources=sources,
                latency_ms=latency_ms,
                model=model_name,
                retrieval_debug=retrieval_debug,
                request_latency_ms=request_latency_ms,
                message_id=assistant_message_id,
            ),
        )
        # Legacy completion marker — deprecated; retained for backward compatibility.
        yield "event: done\ndata: [DONE]\n\n"
        logger.info(f"Answer stream generated successfully for document {doc_id}")

    except asyncio.CancelledError:
        raise
    except RetrievalPresetNotFoundError as e:
        yield _format_sse_event(
            "error",
            _build_stream_error_payload(
                code="preset_not_found",
                message=str(e),
            ),
        )
    except InvalidRetrievalConfigError as e:
        yield _format_sse_event(
            "error",
            _build_stream_error_payload(
                code="invalid_retrieval_config",
                message=str(e),
            ),
        )
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
    debug_retrieval: bool = False,
) -> list[dict]:
    """
    Process multiple question/document retrieval requests in one call.

    Note: The `session_context` provided is shared across all queries in the batch.
    It is assumed that a batch does not mix queries from different sessions.
    """
    if not queries:
        return []

    tenant_id = require_current_tenant(auth)

    normalized_queries = validate_and_normalize_batch_queries(queries)
    for query in normalized_queries:
        if query.get("scope") is None:
            query["scope"] = scope

    effective_configs: list[EffectiveRetrievalConfig] = []
    for query in normalized_queries:
        effective = resolve_effective_retrieval(
            match_count=query["match_count"],
            scope=query.get("scope"),
            retrieval_fields=query["retrieval_fields"] if "retrieval_fields" in query else None,
        )
        effective_configs.append(
            _apply_compare_history_policy(
                effective,
                compare_style=_is_compare_style_batch_query(query["doc_ids"]),
            )
        )

    batch_llm_semaphore = _get_batch_llm_semaphore()

    async def _batch_transform(
        question: str,
        history: list[dict] | None,
        effective_config: EffectiveRetrievalConfig | None = None,
        resolution_policy=None,
        history_observation=None,
    ):
        async with batch_llm_semaphore:
            transform_kwargs = {}
            if effective_config is not None:
                transform_kwargs["effective_config"] = effective_config
            if resolution_policy is not None:
                transform_kwargs["resolution_policy"] = resolution_policy
            if history_observation is not None:
                transform_kwargs["history_observation"] = history_observation
            return await transform_query(question, history=history, **transform_kwargs)

    async def _batch_generate(question: str, context: str):
        async with batch_llm_semaphore:
            return await generate_answer(question, context)

    # Pre-load session histories so each query's transformation can resolve
    # follow-up references.  One DB round-trip per unique session_id.
    async def _load_batch_history(
        session_id: str | None, history_fields: dict | None
    ) -> list[dict]:
        if not session_id:
            return []
        import db
        try:
            return await db.get_session_history(
                session_id=session_id,
                limit=history_load_limit(history_fields),
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
            *[
                _load_batch_history(q.get("session_id"), q.get("history_fields"))
                for q in normalized_queries
            ]
        )
    )
    history_plans = [
        prepare_turn_history(
            loaded,
            query.get("history_fields"),
            skip_history_transform=effective.skip_history_transform,
            apply_generation_history=not _is_compare_style_batch_query(query["doc_ids"]),
            global_query_transformation_enabled=bool(config.QUERY_TRANSFORMATION_ENABLED),
        )
        for query, loaded, effective in zip(
            normalized_queries, per_query_histories, effective_configs
        )
    ]

    transform_results = await asyncio.gather(
        *[
            _batch_transform(
                q["question"],
                history=plan.transform_history,
                effective_config=(
                    effective if transformation_is_request_scoped(effective) else None
                ),
                resolution_policy=plan.policy,
                history_observation=plan.observation,
            )
            for q, plan, effective in zip(
                normalized_queries, history_plans, effective_configs
            )
        ]
    )
    transformed_query_lists = [result.queries for result in transform_results]
    flat_queries = [q for queries in transformed_query_lists for q in queries]
    try:
        flat_embeddings = await get_embeddings(flat_queries, tenant_id=tenant_id)
    except Exception as e:
        logger.error("Batch embedding call failed: %s", e, exc_info=True)
        embedding_message = "Failed to generate embeddings for batch request."
        return [
            {
                "status": "error",
                "question": query["question"],
                "doc_ids": query["doc_ids"],
                "chunks": 0,
                "error": {
                    "code": "embedding_failed",
                    "message": embedding_message,
                },
                "latency_ms": 0,
                "model": "",
                "session_id": query.get("session_id"),
            }
            for query in normalized_queries
        ]
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
        query: dict,
        query_embeddings: list[list[float]],
        generation_history: list[dict],
        transform_result: QueryTransformResult,
        effective: EffectiveRetrievalConfig,
    ) -> dict:
        try:
            session_id = query.get("session_id")
            doc_ids = await _resolve_retrieval_doc_ids(
                scope=effective.scope,
                requested_doc_ids=query["doc_ids"],
                session_id=session_id,
                tenant_id=tenant_id,
                metadata_filter=effective.metadata_filter,
            )
            scope_error = _scope_error(
                doc_ids,
                requested_doc_ids=query["doc_ids"],
                effective=effective,
            )
            if scope_error is not None:
                return {
                    "status": "error",
                    "question": query["question"],
                    "doc_ids": query["doc_ids"],
                    "chunks": 0,
                    "error": scope_error,
                    "latency_ms": 0,
                    "model": "",
                    "session_id": session_id,
                }

            is_compare_style = _is_compare_style_batch_query(query["doc_ids"])
            query_session_context = session_context
            if generation_history and not is_compare_style:
                from copy import deepcopy
                query_session_context = deepcopy(session_context) if session_context else SessionContext()
                query_session_context.chat_history = generation_history

            retrieval = await retrieve_for_documents(
                query["question"],
                doc_ids,
                tenant_id,
                effective,
                session_id=session_id,
                session_context=query_session_context,
                transform_result=transform_result,
                query_embeddings=query_embeddings,
            )
            matching_chunks = retrieval.chunks
            context = retrieval.context
            answer, latency_ms, model_name = await _batch_generate(query["question"], context)

            sources = _build_sources(matching_chunks)
            retrieval_debug = retrieval.to_debug_dict() if debug_retrieval else None
            llm_err = _structured_error_from_llm_answer(answer)
            if llm_err is not None:
                error_payload = {
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
                if retrieval_debug is not None:
                    error_payload["retrieval_debug"] = retrieval_debug
                return error_payload

            if session_id and not is_compare_style:
                try:
                    import db
                    await db.store_chat_turn(
                        session_id=session_id,
                        question=query["question"],
                        answer=answer,
                        tenant_id=tenant_id,
                        sources=_build_source_snapshot(matching_chunks, sources),
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to store batch chat turn for session {session_id}: {e}",
                        exc_info=True,
                    )

            result_payload = {
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
            if retrieval_debug is not None:
                result_payload["retrieval_debug"] = retrieval_debug
            return result_payload
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
            _process_query(query, embeddings, plan.generation_history, transform_result, effective)
            for query, embeddings, plan, transform_result, effective in zip(
                normalized_queries,
                per_query_embeddings,
                history_plans,
                transform_results,
                effective_configs,
            )
        ]
    )

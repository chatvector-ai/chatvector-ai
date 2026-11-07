import logging
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

import db
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from core.auth import AuthContext, require_auth, require_current_tenant
from core.config import config
from middleware.rate_limit import limiter
from pydantic import AfterValidator, BaseModel, Field

from services.chat_service import (
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
    merge_batch_results,
    prepare_batch_chat_items,
    resolve_effective_retrieval,
)
from services.history_config import HISTORY_FIELD_NAMES, merge_history_fields
from services.metadata_filter import validate_metadata_filter
from services.retrieval_config import InvalidRetrievalConfigError, merge_retrieval_field_layers
from services.retrieval_presets import RetrievalPresetNotFoundError
from services.session_service import get_or_create_session, register_session_document
from services.tenant_registry import register_tenant_document

logger = logging.getLogger(__name__)
router = APIRouter()

RetrievalScopeParam = Literal["session", "tenant"]
QueryTransformationStrategyParam = Literal["rewrite", "expand", "stepback", "none"]
RerankerProviderParam = Literal["similarity", "cohere"]
DebugRetrievalQuery = Annotated[bool, Query()]


def _validate_optional_metadata_filter(value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    # ValueError from the validator surfaces as a 422 request validation error.
    return None if value is None else validate_metadata_filter(value)


MetadataFilterParam = Annotated[
    Optional[dict[str, Any]], AfterValidator(_validate_optional_metadata_filter)
]

_RETRIEVAL_FIELD_NAMES = (
    "match_count",
    "scope",
    "hybrid_enabled",
    "reranking_enabled",
    "reranker_provider",
    "query_transformation_enabled",
    "query_transformation_strategy",
    "skip_history_transform",
    "metadata_filter",
)


class RetrievalOverrides(BaseModel):
    """Optional per-request retrieval overrides.

    Top-level request fields win over this object. Omitted fields keep the
    process env default. ``metadata_filter`` narrows which in-scope documents
    participate in retrieval (v1: exact match and scalar ``in`` lists, keys ANDed).
    """

    match_count: Optional[int] = Field(default=None, ge=1, le=20)
    scope: Optional[RetrievalScopeParam] = None
    hybrid_enabled: Optional[bool] = None
    reranking_enabled: Optional[bool] = None
    reranker_provider: Optional[RerankerProviderParam] = None
    query_transformation_enabled: Optional[bool] = None
    query_transformation_strategy: Optional[QueryTransformationStrategyParam] = None
    skip_history_transform: Optional[bool] = None
    metadata_filter: MetadataFilterParam = None
    preset: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Named retrieval preset loaded at process startup.",
    )


class HistoryOverrides(BaseModel):
    """Optional per-request history controls, separate from retrieval config.

    Omitted fields keep the process defaults (``HISTORY_AWARE_RETRIEVAL_DEFAULT``,
    ``QUERY_TRANSFORMATION_HISTORY_WINDOW``, ``GENERATION_HISTORY_WINDOW``).
    ``history_aware_retrieval`` does not enable rewrite, expand, or step-back.
    """

    retrieval_history_window: Optional[int] = Field(default=None, ge=0, le=100)
    generation_history_window: Optional[int] = Field(default=None, ge=0, le=100)
    history_aware_retrieval: Optional[bool] = None
    max_generation_history_chars: Optional[int] = Field(default=None, ge=1, le=1_000_000)


def history_fields_from_model(model: BaseModel) -> dict:
    """Collect an explicitly set nested ``history`` object."""
    history_model = getattr(model, "history", None)
    if history_model is None or "history" not in model.model_fields_set:
        return {}
    fields: dict = {}
    for name in HISTORY_FIELD_NAMES:
        if name in history_model.model_fields_set and getattr(history_model, name) is not None:
            fields[name] = getattr(history_model, name)
    return fields


def retrieval_fields_from_model(model: BaseModel) -> dict:
    """Collect explicitly set retrieval overrides, including a nested object."""
    fields: dict = {}
    for name in _RETRIEVAL_FIELD_NAMES:
        if name in model.model_fields_set and getattr(model, name) is not None:
            fields[name] = getattr(model, name)
    retrieval_model = getattr(model, "retrieval", None)
    if retrieval_model is not None and "retrieval" in model.model_fields_set:
        nested = {}
        for name in _RETRIEVAL_FIELD_NAMES:
            if name in retrieval_model.model_fields_set and getattr(retrieval_model, name) is not None:
                nested[name] = getattr(retrieval_model, name)
        if (
            "preset" in retrieval_model.model_fields_set
            and getattr(retrieval_model, "preset", None) is not None
        ):
            nested["preset"] = getattr(retrieval_model, "preset")
        if nested:
            fields["retrieval"] = nested
    return fields


class ChatSourceResponse(BaseModel):
    """Citation metadata for a retrieved chunk."""

    file_name: Optional[str] = None
    page_number: Optional[int] = None
    chunk_index: Optional[int] = None
    score: Optional[float] = Field(
        default=None,
        description=(
            "Final ranking score for this citation. Interpret using score_type; "
            "raw values are not comparable across vector, hybrid_rrf, and reranked."
        ),
    )
    score_type: Optional[str] = Field(
        default=None,
        description=(
            "What score represents: vector (cosine similarity), hybrid_rrf "
            "(reciprocal rank fusion), or reranked (retrieval + lexical overlap)."
        ),
    )
    vector_score: Optional[float] = Field(
        default=None,
        description=(
            "Cosine similarity from pgvector (1 - distance) when vector search "
            "returned this chunk. Not interchangeable with score or other components."
        ),
    )
    full_text_score: Optional[float] = Field(
        default=None,
        description=(
            "PostgreSQL ts_rank from keyword search when hybrid retrieval matched "
            "this chunk. Uses FTS scale, not vector or RRF scale."
        ),
    )
    rrf_score: Optional[float] = Field(
        default=None,
        description=(
            "Reciprocal Rank Fusion score when hybrid retrieval ran. Small rank-based "
            "values; compare only to other rrf_score fields, not to score or vector_score."
        ),
    )
    reranker_score: Optional[float] = Field(
        default=None,
        description=(
            "Combined normalized retrieval + lexical overlap score when reranking ran. "
            "Becomes the top-level score when score_type is reranked."
        ),
    )
    rerank_order: Optional[int] = Field(
        default=None,
        description="1-based position after reranking when reranking ran.",
    )


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
    hybrid_enabled: Optional[bool] = None
    reranking_enabled: Optional[bool] = None
    reranker_provider: Optional[RerankerProviderParam] = None
    query_transformation_enabled: Optional[bool] = None
    query_transformation_strategy: Optional[QueryTransformationStrategyParam] = None
    skip_history_transform: Optional[bool] = None
    metadata_filter: MetadataFilterParam = None
    retrieval: Optional[RetrievalOverrides] = None
    history: Optional[HistoryOverrides] = None


class ChatBatchRequest(BaseModel):
    queries: list[ChatBatchItem] = Field(..., min_length=1)
    session_id: Optional[str] = None
    scope: RetrievalScopeParam = "session"
    debug_retrieval: bool = False
    hybrid_enabled: Optional[bool] = None
    reranking_enabled: Optional[bool] = None
    reranker_provider: Optional[RerankerProviderParam] = None
    query_transformation_enabled: Optional[bool] = None
    query_transformation_strategy: Optional[QueryTransformationStrategyParam] = None
    skip_history_transform: Optional[bool] = None
    metadata_filter: MetadataFilterParam = None
    retrieval: Optional[RetrievalOverrides] = None
    history: Optional[HistoryOverrides] = None


class ChatResponse(BaseModel):
    question: str
    doc_id: str
    chunks: int
    answer: str
    sources: list[ChatSourceResponse] = Field(default_factory=list)
    latency_ms: int = 0
    model: str = ""
    status: Literal["ok", "error"] = "ok"
    session_id: Optional[str] = None
    error: Optional[dict] = None
    retrieval_debug: Optional[dict] = None


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    doc_id: UUID
    match_count: int = Field(default=5, ge=1, le=20)
    session_id: Optional[str] = None
    scope: RetrievalScopeParam = "session"
    debug_retrieval: bool = False
    hybrid_enabled: Optional[bool] = None
    reranking_enabled: Optional[bool] = None
    reranker_provider: Optional[RerankerProviderParam] = None
    query_transformation_enabled: Optional[bool] = None
    query_transformation_strategy: Optional[QueryTransformationStrategyParam] = None
    skip_history_transform: Optional[bool] = None
    metadata_filter: MetadataFilterParam = None
    retrieval: Optional[RetrievalOverrides] = None
    history: Optional[HistoryOverrides] = None


def _resolve_debug_retrieval(*, query_param: bool, request_field: bool) -> bool:
    return query_param or request_field


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(config.RATE_LIMIT_CHAT)
async def chat(
    request: Request,
    payload: ChatRequest,
    auth: AuthContext = Depends(require_auth),
    debug_retrieval: DebugRetrievalQuery = False,
):
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
        debug_retrieval=_resolve_debug_retrieval(
            query_param=debug_retrieval,
            request_field=payload.debug_retrieval,
        ),
        retrieval_fields=retrieval_fields_from_model(payload),
        history_fields=history_fields_from_model(payload),
    )


@router.post("/chat/stream")
@limiter.limit(config.RATE_LIMIT_CHAT)
async def chat_stream(
    request: Request,
    payload: ChatRequest,
    auth: AuthContext = Depends(require_auth),
    debug_retrieval: DebugRetrievalQuery = False,
):
    """Stream a chat answer as Server-Sent Events (SSE).

    Requires ``ENABLE_STREAMING=true``. Event contract:

    - ``token`` — incremental answer text; ``data`` is a JSON-encoded string
      (unchanged from earlier clients).
    - ``complete`` — final structured payload with ``sources``, ``latency_ms``
      (generation only), ``request_latency_ms`` (full request including history
      and retrieval), ``model``, ``session_id``, optional ``retrieval_debug``
      when requested, and optional ``message_id``. ``message_id`` is the
      persisted assistant message id. It is present only after that message
      is stored successfully, and omitted when the turn is not persisted
      (no session, or a failed store). A missing ``message_id`` is not an error.
    - ``done`` — legacy completion marker ``[DONE]`` (deprecated; retained for
      backward compatibility).
    - ``error`` — structured JSON object ``{"type": "error", "code": "...", "message": "..."}``.
      Terminal: may follow ``token`` events; no ``complete`` or ``done`` is emitted.

    Interrupted streams (client disconnect, cancellation, or provider failure
    mid-stream) do not persist assistant messages. Successful streams persist
    the user/assistant turn atomically before the ``complete`` event is emitted.
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

    retrieval_fields = retrieval_fields_from_model(payload)
    history_fields = history_fields_from_model(payload)
    # Resolve before SSE starts so unknown/invalid presets are HTTP 400, not 200 empty.
    resolve_effective_retrieval(
        match_count=payload.match_count,
        scope=payload.scope,
        retrieval_fields=retrieval_fields,
    )

    return StreamingResponse(
        answer_question_stream_for_document(
            question=payload.question,
            doc_id=doc_id_str,
            match_count=payload.match_count,
            auth=auth,
            session_id=session.id,
            scope=payload.scope,
            debug_retrieval=_resolve_debug_retrieval(
                query_param=debug_retrieval,
                request_field=payload.debug_retrieval,
            ),
            retrieval_fields=retrieval_fields,
            history_fields=history_fields,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/batch")
@limiter.limit(config.RATE_LIMIT_CHAT_BATCH)
async def chat_batch(
    request: Request,
    payload: ChatBatchRequest,
    auth: AuthContext = Depends(require_auth),
    debug_retrieval: DebugRetrievalQuery = False,
):
    logger.info(f"Batch chat request received with {len(payload.queries)} queries")

    # Shared session for the batch if provided at top level, otherwise uses individual
    batch_session_id = payload.session_id

    tenant_id = require_current_tenant(auth)

    try:
        batch_fields = retrieval_fields_from_model(payload)
        batch_history = history_fields_from_model(payload)
        raw_queries = []
        for q in payload.queries:
            q_dict = q.model_dump(mode="json")
            if "scope" not in q.model_fields_set:
                q_dict.pop("scope", None)
            q_dict["retrieval_fields"] = merge_retrieval_field_layers(
                retrieval_fields_from_model(q),
                batch_fields,
            )
            q_dict["history_fields"] = merge_history_fields(
                history_fields_from_model(q),
                batch_history,
            )
            raw_queries.append(q_dict)

        service_items, slot_results = await prepare_batch_chat_items(
            raw_queries,
            tenant_id=tenant_id,
            batch_session_id=batch_session_id,
        )
        service_indices = [index for index, _ in service_items]
        service_queries = [query for _, query in service_items]

        if service_queries:
            service_results = await answer_questions_for_documents_batch(
                service_queries,
                auth=auth,
                scope=payload.scope,
                debug_retrieval=_resolve_debug_retrieval(
                    query_param=debug_retrieval,
                    request_field=payload.debug_retrieval,
                ),
            )
        else:
            service_results = []

        results = merge_batch_results(slot_results, service_indices, service_results)
    except InvalidRetrievalConfigError:
        raise
    except RetrievalPresetNotFoundError:
        raise
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

"""Tests for the ``metadata_filter`` retrieval override (grammar, config, scope, chat)."""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.auth import AuthContext, require_auth
from main import request_validation_exception_handler
from middleware.rate_limit import limiter
from routes.chat import (
    ChatBatchItem,
    ChatBatchRequest,
    ChatRequest,
    RetrievalOverrides,
    retrieval_fields_from_model,
)
from routes.chat import router as chat_router
from services.chat_service import (
    ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_MESSAGE,
    _resolve_retrieval_doc_ids,
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
)
from services.metadata_filter import InvalidMetadataFilterError, validate_metadata_filter
from services.retrieval_config import (
    InvalidRetrievalConfigError,
    RetrievalProcessDefaults,
    merge_retrieval_field_layers,
    resolve_retrieval_config,
)
from services.tenant_registry import clear_tenant_registry, register_tenant_document

_DOC_ID = "00000000-0000-0000-0000-000000000001"
_ENV = RetrievalProcessDefaults()
_FILTER = {"department": "legal"}

MALFORMED_FILTERS = [
    [],  # array instead of object
    "department=legal",
    {},  # empty object
    {"": "legal"},  # empty key
    {"department": None},
    {"department": ["legal", "hr"]},  # array operand
    {"department": {"legal": "hr"}},  # nested object, unknown operator
    {"department": {"in": "legal"}},  # `in` needs a list
    {"department": {"in": []}},  # empty in-list
    {"department": {"in": [["legal"]]}},  # nested array inside in-list
    {"department": {"in": [{"a": 1}]}},  # object inside in-list
    {"department": {"in": ["legal"], "eq": "x"}},  # extra operator
    {"department": {"gt": 3}},  # unsupported operator
    {"department": {"nested": {"a": 1}}},
    {"department": float("nan")},
    {"department": float("inf")},
    {"department": "bad\x00value"},
    {"bad\x00key": "legal"},
]


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_tenant_registry()
    yield
    clear_tenant_registry()


@pytest.fixture(autouse=True)
def _disable_query_transformation(monkeypatch):
    import services.chat_service as chat_service_mod

    monkeypatch.setattr(chat_service_mod.config, "QUERY_TRANSFORMATION_ENABLED", False)


# ── grammar ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        {"department": "legal"},
        {"year": 2026},
        {"score": 1.5},
        {"final": True},
        {"final": False},
        {"department": {"in": ["legal", "hr"]}},
        {"year": {"in": [2025, 2026]}},
        {"mixed": {"in": ["a", 1, 2.5, True]}},
        {"department": "legal", "year": 2026, "tier": {"in": ["a", "b"]}},
    ],
)
def test_validate_accepts_v1_grammar(raw):
    assert validate_metadata_filter(raw) == raw


def test_validate_returns_independent_copy():
    raw = {"department": {"in": ["legal"]}}
    normalized = validate_metadata_filter(raw)
    raw["department"]["in"].append("hr")
    assert normalized == {"department": {"in": ["legal"]}}


@pytest.mark.parametrize("raw", MALFORMED_FILTERS)
def test_validate_rejects_malformed(raw):
    with pytest.raises(InvalidMetadataFilterError):
        validate_metadata_filter(raw)


def test_validate_enforces_key_and_size_bounds(monkeypatch):
    # Patch the config object the validator actually holds (core.config can be reloaded by other tests).
    from services.metadata_filter import config

    monkeypatch.setattr(config, "DOCUMENT_METADATA_MAX_KEYS", 2)
    assert validate_metadata_filter({"a": 1, "b": 2}) == {"a": 1, "b": 2}
    with pytest.raises(InvalidMetadataFilterError, match="at most 2 keys"):
        validate_metadata_filter({"a": 1, "b": 2, "c": 3})

    monkeypatch.setattr(config, "DOCUMENT_METADATA_MAX_KEYS", 20)
    monkeypatch.setattr(config, "DOCUMENT_METADATA_MAX_BYTES", 32)
    with pytest.raises(InvalidMetadataFilterError, match="maximum size"):
        validate_metadata_filter({"department": {"in": ["a" * 40]}})


# ── effective retrieval config ───────────────────────────────────────────────


def test_omitted_filter_leaves_effective_config_unchanged():
    effective = resolve_retrieval_config({"match_count": 7}, _ENV)

    assert effective.metadata_filter is None
    assert effective.sources["metadata_filter"] == "env"
    assert "metadata_filter" not in effective.to_debug_dict()


def test_filter_resolves_from_top_level_and_nested_object():
    top = resolve_retrieval_config({"metadata_filter": _FILTER}, _ENV)
    nested = resolve_retrieval_config({"retrieval": {"metadata_filter": _FILTER}}, _ENV)

    for effective in (top, nested):
        assert effective.metadata_filter == _FILTER
        assert effective.sources["metadata_filter"] == "request"
        assert effective.to_debug_dict()["metadata_filter"] == {
            "value": _FILTER,
            "source": "request",
        }


def test_top_level_filter_wins_over_nested_filter():
    effective = resolve_retrieval_config(
        {"metadata_filter": {"a": 1}, "retrieval": {"metadata_filter": {"b": 2}}}, _ENV
    )
    assert effective.metadata_filter == {"a": 1}


def test_batch_item_filter_wins_over_batch_level_filter():
    merged = merge_retrieval_field_layers(
        {"metadata_filter": {"a": 1}},
        {"metadata_filter": {"b": 2}},
    )
    assert merged == {"metadata_filter": {"a": 1}}
    assert merge_retrieval_field_layers({}, {"metadata_filter": {"b": 2}}) == {
        "retrieval": {"metadata_filter": {"b": 2}}
    }


@pytest.mark.parametrize("raw", MALFORMED_FILTERS)
def test_resolve_rejects_malformed_filter(raw):
    with pytest.raises(InvalidRetrievalConfigError):
        resolve_retrieval_config({"metadata_filter": raw}, _ENV)


# ── request validation (422) ─────────────────────────────────────────────────


def test_request_models_accept_valid_filter_top_level_and_nested():
    top = ChatRequest(question="q", doc_id=_DOC_ID, metadata_filter=_FILTER)
    nested = ChatRequest(
        question="q", doc_id=_DOC_ID, retrieval={"metadata_filter": _FILTER}
    )

    assert retrieval_fields_from_model(top) == {"metadata_filter": _FILTER}
    assert retrieval_fields_from_model(nested) == {"retrieval": {"metadata_filter": _FILTER}}


def test_request_models_omit_filter_by_default():
    request = ChatRequest(question="q", doc_id=_DOC_ID)

    assert request.metadata_filter is None
    assert "metadata_filter" not in retrieval_fields_from_model(request)


@pytest.mark.parametrize("raw", MALFORMED_FILTERS)
def test_request_models_reject_malformed_filter(raw):
    with pytest.raises(ValidationError):
        ChatRequest(question="q", doc_id=_DOC_ID, metadata_filter=raw)
    with pytest.raises(ValidationError):
        ChatRequest(question="q", doc_id=_DOC_ID, retrieval={"metadata_filter": raw})
    with pytest.raises(ValidationError):
        ChatBatchItem(question="q", doc_ids=[_DOC_ID], metadata_filter=raw)
    with pytest.raises(ValidationError):
        ChatBatchRequest(
            queries=[ChatBatchItem(question="q", doc_ids=[_DOC_ID])], metadata_filter=raw
        )


@pytest.fixture
def client():
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.include_router(chat_router)
    app.dependency_overrides[require_auth] = lambda: AuthContext(tenant_id="tenant-a")
    with TestClient(app) as c:
        yield c
    limiter.reset()


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
@pytest.mark.parametrize(
    "body",
    [
        {"metadata_filter": ["legal"]},
        {"metadata_filter": {"department": {"nested": {"a": 1}}}},
        {"metadata_filter": {"department": ["legal"]}},
        {"retrieval": {"metadata_filter": {"department": {"in": "legal"}}}},
    ],
)
def test_chat_routes_return_422_for_malformed_filter(client, path, body):
    payload = {"question": "q", "doc_id": _DOC_ID, **body}
    with patch("routes.chat.answer_question_for_document", new=AsyncMock()) as answer:
        response = client.post(path, json=payload)

    assert response.status_code == 422
    assert any("metadata_filter" in field["loc"] for field in response.json()["detail"]["fields"])
    answer.assert_not_awaited()


def test_chat_batch_returns_422_for_malformed_filter(client):
    payload = {
        "queries": [{"question": "q", "doc_ids": [_DOC_ID], "metadata_filter": {"a": [1]}}]
    }
    response = client.post("/chat/batch", json=payload)

    assert response.status_code == 422
    assert any("metadata_filter" in field["loc"] for field in response.json()["detail"]["fields"])


def test_chat_route_passes_valid_filter_and_still_requires_anchor_doc_id(client):
    with patch(
        "routes.chat.answer_question_for_document",
        new=AsyncMock(
            return_value={
                "question": "q",
                "doc_id": _DOC_ID,
                "chunks": 0,
                "answer": "a",
                "status": "ok",
            }
        ),
    ) as answer, patch(
        "routes.chat._assert_document_owned", new=AsyncMock()
    ), patch(
        "routes.chat.get_or_create_session",
        new=AsyncMock(return_value=type("S", (), {"id": "sess-1"})()),
    ), patch("routes.chat.register_session_document", new=AsyncMock()), patch(
        "routes.chat.register_tenant_document"
    ):
        ok = client.post(
            "/chat",
            json={"question": "q", "doc_id": _DOC_ID, "metadata_filter": _FILTER},
        )
        missing_anchor = client.post(
            "/chat", json={"question": "q", "metadata_filter": _FILTER}
        )

    assert ok.status_code == 200
    assert answer.await_args.kwargs["retrieval_fields"] == {"metadata_filter": _FILTER}
    assert missing_anchor.status_code == 422


# ── scoped document ID resolution ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_applies_filter_to_scoped_candidates():
    register_tenant_document("tenant-a", "doc-1")
    register_tenant_document("tenant-a", "doc-2")
    register_tenant_document("tenant-a", "doc-3")
    filter_docs = AsyncMock(return_value=["doc-1", "doc-3"])

    with patch("services.chat_service.filter_document_ids_by_metadata", new=filter_docs):
        result = await _resolve_retrieval_doc_ids(
            scope="tenant",
            requested_doc_ids=["doc-1"],
            tenant_id="tenant-a",
            metadata_filter=_FILTER,
        )

    assert result == ["doc-1", "doc-3"]
    filter_docs.assert_awaited_once_with(
        tenant_id="tenant-a",
        doc_ids=["doc-1", "doc-2", "doc-3"],
        metadata_filter=_FILTER,
    )


@pytest.mark.asyncio
async def test_resolve_without_filter_never_queries_metadata():
    register_tenant_document("tenant-a", "doc-1")
    register_tenant_document("tenant-a", "doc-2")
    filter_docs = AsyncMock()

    with patch("services.chat_service.filter_document_ids_by_metadata", new=filter_docs):
        result = await _resolve_retrieval_doc_ids(
            scope="tenant",
            requested_doc_ids=["doc-1"],
            tenant_id="tenant-a",
        )

    assert result == ["doc-1", "doc-2"]
    filter_docs.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_skips_metadata_query_when_scope_is_empty():
    filter_docs = AsyncMock()

    with patch(
        "services.chat_service.get_tenant_document_ids", new=AsyncMock(return_value=["doc-x"])
    ), patch("services.chat_service.filter_document_ids_by_metadata", new=filter_docs):
        result = await _resolve_retrieval_doc_ids(
            scope="session",
            requested_doc_ids=[],
            tenant_id="tenant-a",
            metadata_filter=_FILTER,
        )

    assert result == []
    filter_docs.assert_not_awaited()


# ── chat flow ────────────────────────────────────────────────────────────────


def _chat_patches(find_similar):
    return (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])),
        patch("services.chat_service.find_similar_chunks", new=find_similar),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(return_value=("answer", 1, "m")),
        ),
    )


def _register_docs(tenant_id: str, *doc_ids: str) -> None:
    for doc_id in doc_ids:
        register_tenant_document(tenant_id, doc_id)


@pytest.mark.asyncio
async def test_chat_filter_narrows_searched_documents_but_keeps_anchor():
    _register_docs("tenant-a", "doc-1", "doc-2", "doc-3")
    find_similar = AsyncMock(return_value=[])
    filter_docs = AsyncMock(return_value=["doc-1", "doc-3"])
    p1, p2, p3, p4 = _chat_patches(find_similar)

    with p1, p2, p3, p4, patch(
        "services.chat_service.filter_document_ids_by_metadata", new=filter_docs
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="tenant-a"),
            scope="tenant",
            retrieval_fields={"scope": "tenant", "metadata_filter": _FILTER},
        )

    assert result["status"] == "ok"
    assert {call.kwargs["doc_id"] for call in find_similar.await_args_list} == {"doc-1", "doc-3"}


@pytest.mark.asyncio
async def test_chat_anchor_outside_filtered_scope_returns_structured_error():
    _register_docs("tenant-a", "doc-1", "doc-2")
    find_similar = AsyncMock(return_value=[])
    p1, p2, p3, p4 = _chat_patches(find_similar)

    with p1, p2, p3, p4, patch(
        "services.chat_service.filter_document_ids_by_metadata",
        new=AsyncMock(return_value=["doc-2"]),
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="tenant-a"),
            scope="tenant",
            retrieval_fields={"scope": "tenant", "metadata_filter": _FILTER},
        )

    assert result["status"] == "error"
    assert result["doc_id"] == "doc-1"
    assert result["error"]["code"] == "anchor_document_excluded_by_filter"
    assert result["error"]["message"] == ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_MESSAGE
    find_similar.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_filter_matching_nothing_returns_anchor_error():
    _register_docs("tenant-a", "doc-1")
    find_similar = AsyncMock(return_value=[])
    p1, p2, p3, p4 = _chat_patches(find_similar)

    with p1, p2, p3, p4, patch(
        "services.chat_service.filter_document_ids_by_metadata",
        new=AsyncMock(return_value=[]),
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="tenant-a"),
            scope="session",
            retrieval_fields={"metadata_filter": _FILTER},
        )

    assert result["error"]["code"] == "anchor_document_excluded_by_filter"
    assert result["error"]["message"] == ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_MESSAGE
    find_similar.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_without_filter_is_unchanged_and_skips_metadata_lookup():
    _register_docs("tenant-a", "doc-1", "doc-2")
    find_similar = AsyncMock(return_value=[])
    filter_docs = AsyncMock()
    p1, p2, p3, p4 = _chat_patches(find_similar)

    with p1, p2, p3, p4, patch(
        "services.chat_service.filter_document_ids_by_metadata", new=filter_docs
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="tenant-a"),
            scope="tenant",
        )

    assert result["status"] == "ok"
    assert {call.kwargs["doc_id"] for call in find_similar.await_args_list} == {"doc-1", "doc-2"}
    filter_docs.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_filter_narrows_documents():
    _register_docs("tenant-a", "doc-1", "doc-2")
    find_similar = AsyncMock(return_value=[])
    p1, p2, p3, _ = _chat_patches(find_similar)

    async def fake_stream(question, context):
        yield "hi"

    with p1, p2, p3, patch(
        "services.chat_service.generate_answer_stream", new=fake_stream
    ), patch(
        "services.chat_service.filter_document_ids_by_metadata",
        new=AsyncMock(return_value=["doc-1"]),
    ), patch("services.providers.get_llm_provider", return_value=type("P", (), {"model_name": "m"})()):
        events = [
            event
            async for event in answer_question_stream_for_document(
                question="Q?",
                doc_id="doc-1",
                auth=AuthContext(tenant_id="tenant-a"),
                scope="tenant",
                retrieval_fields={"scope": "tenant", "metadata_filter": _FILTER},
            )
        ]

    assert any(event.startswith("event: complete") for event in events)
    assert {call.kwargs["doc_id"] for call in find_similar.await_args_list} == {"doc-1"}


@pytest.mark.asyncio
async def test_stream_anchor_outside_filtered_scope_emits_error_event():
    _register_docs("tenant-a", "doc-1", "doc-2")
    find_similar = AsyncMock(return_value=[])
    p1, p2, p3, p4 = _chat_patches(find_similar)

    with p1, p2, p3, p4, patch(
        "services.chat_service.filter_document_ids_by_metadata",
        new=AsyncMock(return_value=["doc-2"]),
    ):
        events = [
            event
            async for event in answer_question_stream_for_document(
                question="Q?",
                doc_id="doc-1",
                auth=AuthContext(tenant_id="tenant-a"),
                scope="tenant",
                retrieval_fields={"scope": "tenant", "metadata_filter": _FILTER},
            )
        ]

    assert len(events) == 1
    assert events[0].startswith("event: error")
    stream_error = json.loads(events[0].split("data: ", 1)[1])
    assert stream_error["code"] == "anchor_document_excluded_by_filter"
    assert stream_error["message"] == ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_MESSAGE
    find_similar.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_item_filter_narrows_documents_and_reports_empty_scope():
    _register_docs("tenant-a", "doc-1", "doc-2", "doc-3")
    find_similar = AsyncMock(return_value=[])

    async def fake_filter(*, tenant_id, doc_ids, metadata_filter):
        return [d for d in doc_ids if d != "doc-2"] if metadata_filter == _FILTER else []

    queries = [
        {
            "question": "Q1",
            "doc_ids": ["doc-1"],
            "retrieval_fields": {"scope": "tenant", "metadata_filter": _FILTER},
        },
        {
            "question": "Q2",
            "doc_ids": ["doc-1"],
            "retrieval_fields": {"scope": "tenant", "metadata_filter": {"department": "none"}},
        },
    ]
    p1, p2, p3, p4 = _chat_patches(find_similar)

    async def fake_embeddings(texts, **kwargs):
        return [[0.1, 0.2] for _ in texts]

    with p1, p2, p3, p4, patch(
        "services.chat_service.get_embeddings", new=fake_embeddings
    ), patch("services.chat_service.filter_document_ids_by_metadata", new=fake_filter):
        results = await answer_questions_for_documents_batch(
            queries, auth=AuthContext(tenant_id="tenant-a"), scope="tenant"
        )

    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "error"
    assert results[1]["error"]["code"] == "anchor_document_excluded_by_filter"
    assert results[1]["error"]["message"] == ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_MESSAGE
    assert {call.kwargs["doc_id"] for call in find_similar.await_args_list} == {"doc-1", "doc-3"}


@pytest.mark.asyncio
async def test_batch_anchor_exclusion_matches_sync_error_code():
    _register_docs("tenant-a", "doc-1", "doc-2")
    find_similar = AsyncMock(return_value=[])
    p1, p2, p3, p4 = _chat_patches(find_similar)

    with p1, p2, p3, p4, patch(
        "services.chat_service.filter_document_ids_by_metadata",
        new=AsyncMock(return_value=["doc-2"]),
    ), patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])):
        sync = await answer_question_for_document(
            question="Q?",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="tenant-a"),
            scope="tenant",
            retrieval_fields={"scope": "tenant", "metadata_filter": _FILTER},
        )
        batch = await answer_questions_for_documents_batch(
            [
                {
                    "question": "Q?",
                    "doc_ids": ["doc-1"],
                    "retrieval_fields": {"scope": "tenant", "metadata_filter": _FILTER},
                }
            ],
            auth=AuthContext(tenant_id="tenant-a"),
            scope="tenant",
        )

    assert sync["error"]["code"] == "anchor_document_excluded_by_filter"
    assert sync["error"]["message"] == ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_MESSAGE
    assert batch[0]["error"]["code"] == sync["error"]["code"]
    assert batch[0]["error"]["message"] == sync["error"]["message"]


def test_retrieval_overrides_model_accepts_filter():
    overrides = RetrievalOverrides(metadata_filter=_FILTER)
    assert overrides.metadata_filter == _FILTER


# ── db wrapper ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_db_wrapper_delegates_to_service_with_tenant():
    import db

    service = type("Svc", (), {})()
    service.filter_document_ids_by_metadata = AsyncMock(return_value=["doc-1"])

    with patch("db.get_db_service", return_value=service):
        result = await db.filter_document_ids_by_metadata("tenant-a", ["doc-1", "doc-2"], _FILTER)

    assert result == ["doc-1"]
    service.filter_document_ids_by_metadata.assert_awaited_once_with(
        "tenant-a", ["doc-1", "doc-2"], _FILTER
    )


@pytest.mark.asyncio
async def test_db_wrapper_requires_tenant_id():
    import db

    service = type("Svc", (), {})()
    service.filter_document_ids_by_metadata = AsyncMock()

    with patch("db.get_db_service", return_value=service), pytest.raises(ValueError):
        await db.filter_document_ids_by_metadata("", ["doc-1"], _FILTER)

    service.filter_document_ids_by_metadata.assert_not_awaited()


# ── real database: filtered scope with differing metadata ────────────────────

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
)


async def _metadata_column_exists() -> bool:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(DB_URL, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='documents' "
                    "AND column_name='metadata'"
                )
            )
            return result.scalar_one() == 1
    except Exception:
        return False
    finally:
        await engine.dispose()


_requires_metadata_column = pytest.mark.skipif(
    not asyncio.get_event_loop().run_until_complete(_metadata_column_exists())
    if sys.platform != "win32"
    else False,
    reason="documents.metadata column not available (apply 013_document_metadata.sql)",
)


@pytest.fixture
async def metadata_docs():
    """Tenant A with three documents of differing metadata; tenant B with one."""
    pytest.importorskip("pgvector")
    from core.models import Document, Tenant
    from db.sqlalchemy_service import SQLAlchemyService
    from services.api_key_service import ensure_tenant_exists
    from sqlalchemy import delete

    svc = SQLAlchemyService()
    tenant_a = f"mf-a-{uuid4().hex[:8]}"
    tenant_b = f"mf-b-{uuid4().hex[:8]}"
    await ensure_tenant_exists(tenant_a, "Filter A")
    await ensure_tenant_exists(tenant_b, "Filter B")

    docs = {
        "legal": await svc.create_document(
            "legal.pdf",
            tenant_id=tenant_a,
            metadata={"department": "legal", "year": 2026, "final": True},
        ),
        "hr": await svc.create_document(
            "hr.pdf", tenant_id=tenant_a, metadata={"department": "hr", "year": 2025}
        ),
        "eng": await svc.create_document(
            "eng.pdf",
            tenant_id=tenant_a,
            metadata={"department": "eng", "year": 2026, "score": 1.5},
        ),
        "bare": await svc.create_document("bare.pdf", tenant_id=tenant_a),
    }
    foreign = await svc.create_document(
        "foreign.pdf", tenant_id=tenant_b, metadata={"department": "legal", "year": 2026}
    )
    try:
        yield svc, tenant_a, tenant_b, docs, foreign
    finally:
        async with svc.async_session() as session:
            async with session.begin():
                for tenant in (tenant_a, tenant_b):
                    await session.execute(delete(Document).where(Document.tenant_id == tenant))
                    await session.execute(delete(Tenant).where(Tenant.id == tenant))
        await svc.engine.dispose()


async def _ids(svc, tenant_id, doc_ids, metadata_filter):
    return await svc.filter_document_ids_by_metadata(tenant_id, doc_ids, metadata_filter)


@_requires_metadata_column
@pytest.mark.asyncio
async def test_db_filter_exact_in_and_and_semantics(metadata_docs):
    svc, tenant_a, _, docs, _ = metadata_docs
    all_ids = list(docs.values())

    assert await _ids(svc, tenant_a, all_ids, {"department": "legal"}) == [docs["legal"]]
    assert set(
        await _ids(svc, tenant_a, all_ids, {"department": {"in": ["legal", "hr"]}})
    ) == {docs["legal"], docs["hr"]}
    assert set(await _ids(svc, tenant_a, all_ids, {"year": 2026})) == {docs["legal"], docs["eng"]}
    assert await _ids(svc, tenant_a, all_ids, {"year": 2026, "department": "eng"}) == [docs["eng"]]
    assert await _ids(svc, tenant_a, all_ids, {"year": 2025, "department": "legal"}) == []
    assert await _ids(svc, tenant_a, all_ids, {"final": True}) == [docs["legal"]]
    assert await _ids(svc, tenant_a, all_ids, {"score": 1.5}) == [docs["eng"]]
    assert set(
        await _ids(svc, tenant_a, all_ids, {"year": {"in": [2025, 2026]}, "department": {"in": ["hr", "eng"]}})
    ) == {docs["hr"], docs["eng"]}


@_requires_metadata_column
@pytest.mark.asyncio
async def test_db_filter_is_same_type_case_sensitive_and_requires_key(metadata_docs):
    svc, tenant_a, _, docs, _ = metadata_docs
    all_ids = list(docs.values())

    assert await _ids(svc, tenant_a, all_ids, {"department": "LEGAL"}) == []
    assert await _ids(svc, tenant_a, all_ids, {"year": "2026"}) == []
    assert await _ids(svc, tenant_a, all_ids, {"final": "true"}) == []
    assert await _ids(svc, tenant_a, all_ids, {"final": 1}) == []
    assert await _ids(svc, tenant_a, all_ids, {"year": {"in": ["2026"]}}) == []
    assert await _ids(svc, tenant_a, all_ids, {"missing_key": "legal"}) == []
    assert docs["bare"] not in await _ids(svc, tenant_a, all_ids, {"department": {"in": ["x", "eng"]}})


@_requires_metadata_column
@pytest.mark.asyncio
async def test_db_filter_only_considers_given_candidates_and_preserves_order(metadata_docs):
    svc, tenant_a, _, docs, _ = metadata_docs

    result = await _ids(
        svc,
        tenant_a,
        [docs["eng"], "not-a-uuid", docs["legal"], docs["hr"], docs["legal"]],
        {"year": {"in": [2025, 2026]}},
    )
    assert result == [docs["eng"], docs["legal"], docs["hr"]]

    assert await _ids(svc, tenant_a, [docs["hr"]], {"department": "legal"}) == []
    assert await _ids(svc, tenant_a, [], {"department": "legal"}) == []
    assert await _ids(svc, tenant_a, ["not-a-uuid"], {"department": "legal"}) == []


@_requires_metadata_column
@pytest.mark.asyncio
async def test_db_filter_never_crosses_tenants(metadata_docs):
    svc, tenant_a, tenant_b, docs, foreign = metadata_docs

    # A foreign document passed as a candidate is excluded even though it matches.
    assert await _ids(
        svc, tenant_a, [docs["legal"], foreign], {"department": "legal"}
    ) == [docs["legal"]]
    assert await _ids(svc, tenant_a, [foreign], {"department": "legal"}) == []
    assert await _ids(svc, tenant_b, [docs["legal"]], {"department": "legal"}) == []
    assert await _ids(svc, tenant_b, [foreign], {"department": "legal"}) == [foreign]


@_requires_metadata_column
@pytest.mark.asyncio
async def test_filter_excludes_non_matching_docs_from_scoped_retrieval(metadata_docs):
    """End to end on a real DB: tenant-scope chat with a filter searches matching docs only."""
    svc, tenant_a, tenant_b, docs, foreign = metadata_docs
    auth = AuthContext(tenant_id=tenant_a)

    async def run(doc_id, retrieval_fields=None):
        find_similar = AsyncMock(return_value=[])
        p1, p2, p3, p4 = _chat_patches(find_similar)
        with p1, p2, p3, p4, patch(
            "db.list_tenant_documents", new=svc.list_tenant_documents
        ), patch(
            "services.chat_service.filter_document_ids_by_metadata",
            new=svc.filter_document_ids_by_metadata,
        ):
            clear_tenant_registry()
            result = await answer_question_for_document(
                question="Q?",
                doc_id=doc_id,
                auth=auth,
                scope="tenant",
                retrieval_fields={"scope": "tenant", **(retrieval_fields or {})},
            )
        return result, {call.kwargs["doc_id"] for call in find_similar.await_args_list}

    # No filter: Phase 3 behaviour, every tenant document is searched, no foreign docs.
    result, searched = await run(docs["legal"])
    assert result["status"] == "ok"
    assert searched == set(docs.values())
    assert foreign not in searched

    # Filter narrows the scoped documents; tenant B's matching document never appears.
    result, searched = await run(
        docs["legal"], {"metadata_filter": {"department": {"in": ["legal", "hr"]}}}
    )
    assert result["status"] == "ok"
    assert searched == {docs["legal"], docs["hr"]}
    assert foreign not in searched

    result, searched = await run(docs["legal"], {"metadata_filter": {"year": 2026}})
    assert searched == {docs["legal"], docs["eng"]}

    # Anchor must itself be inside the filtered scope.
    result, searched = await run(docs["hr"], {"metadata_filter": {"department": "legal"}})
    assert result["status"] == "error"
    assert result["error"]["code"] == "anchor_document_excluded_by_filter"
    assert result["error"]["message"] == ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_MESSAGE
    assert searched == set()

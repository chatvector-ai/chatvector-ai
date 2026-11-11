"""Behavioral tests for per-request retrieval configuration."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from core.auth import AuthContext
from core.config import config
from core.session import Session
from db.base import SCORE_TYPE_HYBRID_RRF, SCORE_TYPE_VECTOR, ChunkMatch
from request_utils import make_test_request
from routes.chat import ChatRequest, chat
from services.chat_service import (
    _build_sources,
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
    retrieve_for_documents,
)
from services.query_service import QueryTransformResult
from services.retrieval_config import RetrievalProcessDefaults, resolve_retrieval_config
from services.retrieval_presets import reset_retrieval_presets_for_tests, set_retrieval_presets_for_tests

_DOC_ID = "00000000-0000-0000-0000-000000000001"

TEST_AUTH = AuthContext(tenant_id="dev")
PHASE3_ORDER = ("chunk-a", "chunk-b", "chunk-c")


def _chunk(chunk_id: str, text: str, *, index: int, score_type: str = SCORE_TYPE_VECTOR) -> ChunkMatch:
    return ChunkMatch(
        id=chunk_id,
        chunk_text=text,
        document_id="doc-1",
        chunk_index=index,
        similarity=0.5,
        score_type=score_type,
        vector_score=0.5,
        file_name="doc.txt",
    )


def _baseline_chunks() -> list[ChunkMatch]:
    return [
        _chunk(chunk_id, f"text {chunk_id}", index=index)
        for index, chunk_id in enumerate(PHASE3_ORDER)
    ]


@pytest.fixture
def pinned_phase3_env(monkeypatch):
    monkeypatch.setattr(config, "HYBRID_RETRIEVAL_ENABLED", False)
    monkeypatch.setattr(config, "ENABLE_RERANKING", False)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")


@pytest.fixture
def passthrough_docs(monkeypatch):
    async def _passthrough(**kwargs):
        return list(kwargs["requested_doc_ids"])

    monkeypatch.setattr(
        "services.chat_service._resolve_retrieval_doc_ids",
        _passthrough,
    )


def _chat_patches(find_similar):
    return (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])),
        patch("services.chat_service.find_similar_chunks", new=find_similar),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
    )


@pytest.mark.asyncio
async def test_omitted_retrieval_config_matches_phase3_chunk_order(pinned_phase3_env, passthrough_docs):
    """POST /chat with no retrieval config keeps the fixture chunk-id order.

    PHASE3_ORDER is the vector-search baseline for this question and document.
    The response is checked against that constant, not against a second call.
    """
    retrieved_ids: list[str] = []

    def recording_sources(chunks):
        retrieved_ids.extend(chunk.id for chunk in chunks)
        return _build_sources(chunks)

    find_similar = AsyncMock(return_value=_baseline_chunks())
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with (
        embed_patch,
        find_patch,
        answer_patch,
        patch("services.chat_service._build_sources", new=recording_sources),
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": _DOC_ID, "status": "completed"})),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=Session(id="sess-phase3", tenant_id="dev"))),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch("routes.chat.register_tenant_document"),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch("db.store_chat_turn", new=AsyncMock()),
    ):
        response = await chat(
            make_test_request("POST", "/chat"),
            ChatRequest(question="fixed question", doc_id=_DOC_ID),
            auth=TEST_AUTH,
        )

    assert retrieved_ids == list(PHASE3_ORDER)
    assert [source["chunk_index"] for source in response["sources"]] == [0, 1, 2]
    assert all(source["score_type"] == SCORE_TYPE_VECTOR for source in response["sources"])
    assert find_similar.await_args_list
    assert all("hybrid_enabled" not in call.kwargs for call in find_similar.await_args_list)
    assert config.HYBRID_RETRIEVAL_ENABLED is False
    assert config.ENABLE_RERANKING is False
    assert config.QUERY_TRANSFORMATION_ENABLED is False


@pytest.mark.asyncio
async def test_hybrid_request_returns_hybrid_rrf_where_vector_baseline_does_not(
    pinned_phase3_env, passthrough_docs
):
    vector_chunks = _baseline_chunks()
    hybrid_chunks = [
        _chunk("hybrid-hit", "keyword hit", index=0, score_type=SCORE_TYPE_HYBRID_RRF)
    ]

    async def fake_find(**kwargs):
        if kwargs.get("hybrid_enabled"):
            return hybrid_chunks
        return vector_chunks

    find_similar = AsyncMock(side_effect=fake_find)
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with embed_patch, find_patch, answer_patch:
        baseline = await answer_question_for_document(
            question="fixed question",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields={},
        )
        hybrid = await answer_question_for_document(
            question="fixed question",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields={"hybrid_enabled": True},
        )

    assert all(source["score_type"] != SCORE_TYPE_HYBRID_RRF for source in baseline["sources"])
    assert any(source["score_type"] == SCORE_TYPE_HYBRID_RRF for source in hybrid["sources"])
    assert config.HYBRID_RETRIEVAL_ENABLED is False


@pytest.mark.asyncio
async def test_reranking_request_changes_rerank_order(pinned_phase3_env, passthrough_docs):
    chunks = [
        _chunk("low", "unrelated text about cats", index=0),
        _chunk("high", "beta query terms appear here", index=1),
    ]
    find_similar = AsyncMock(return_value=list(chunks))
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with embed_patch, find_patch, answer_patch:
        disabled = await answer_question_for_document(
            question="beta query",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields={"reranking_enabled": False},
        )
        enabled = await answer_question_for_document(
            question="beta query",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields={"reranking_enabled": True, "reranker_provider": "similarity"},
        )

    assert [source["chunk_index"] for source in disabled["sources"]] == [0, 1]
    assert all(source.get("rerank_order") is None for source in disabled["sources"])
    assert [source["rerank_order"] for source in enabled["sources"]] == [1, 2]
    assert enabled["sources"][0]["chunk_index"] == 1
    assert config.ENABLE_RERANKING is False


@pytest.mark.asyncio
async def test_hybrid_keyword_search_uses_effective_retrieval_query(pinned_phase3_env, passthrough_docs):
    """Rewrite changes which keyword chunk is selected.

    The raw question matches raw-only. The rewritten query matches effective-only.
    Hybrid search must return the rewritten match.
    """
    pytest.importorskip("pgvector")
    from db.sqlalchemy_service import SQLAlchemyService

    raw_question = "raw question about widgets"
    effective_query = "effective keyword query"
    raw_only = _chunk("raw-only", "widgets manual", index=0)
    effective_only = _chunk("effective-only", "resolved standalone terms", index=1)
    vector_only = _chunk("vector-only", "shared vector hit", index=2)
    keyword_queries: list[str] = []

    async def fake_keyword(session, doc_id, query_text, limit, tenant_id=None):
        del session, doc_id, limit, tenant_id
        keyword_queries.append(query_text)
        if query_text == effective_query:
            return [effective_only]
        if query_text == raw_question:
            return [raw_only]
        return []

    async def fake_vector(session, doc_id, query_embedding, limit, tenant_id=None):
        del session, doc_id, query_embedding, limit, tenant_id
        return [vector_only]

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    service = SQLAlchemyService()
    service._retrieval_semaphore = asyncio.Semaphore(10)
    service._find_keyword_chunks = fake_keyword
    service._find_vector_chunks = fake_vector
    service.async_session = lambda: _FakeSession()

    raw_hits = await service._find_keyword_chunks(None, "doc-1", raw_question, 5, tenant_id="dev")
    assert [match.id for match in raw_hits] == ["raw-only"]
    keyword_queries.clear()

    async def find_similar(doc_id, query_embedding, match_count, *, tenant_id, session_id=None, query_text=None, hybrid_enabled=None):
        return await service.find_similar_chunks(
            doc_id,
            query_embedding,
            match_count,
            tenant_id=tenant_id,
            session_id=session_id,
            query_text=query_text,
            hybrid_enabled=hybrid_enabled,
        )

    async def fake_rewrite(question: str) -> str:
        del question
        return effective_query

    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with (
        embed_patch,
        find_patch,
        answer_patch,
        patch("services.query_service.rewrite_query", new=fake_rewrite),
    ):
        result = await answer_question_for_document(
            question=raw_question,
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields={
                "hybrid_enabled": True,
                "query_transformation_strategy": "rewrite",
            },
        )

    selected = {source["chunk_index"] for source in result["sources"]}
    assert keyword_queries == [effective_query]
    assert 1 in selected
    assert 0 not in selected
    assert config.HYBRID_RETRIEVAL_ENABLED is False


@pytest.mark.asyncio
async def test_concurrent_requests_keep_independent_hybrid_flags(pinned_phase3_env, passthrough_docs):
    seen: list[bool | None] = []

    async def fake_find(**kwargs):
        await asyncio.sleep(0.01)
        seen.append(kwargs.get("hybrid_enabled"))
        return _baseline_chunks()

    find_similar = AsyncMock(side_effect=fake_find)
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with embed_patch, find_patch, answer_patch:
        await asyncio.gather(
            answer_question_for_document(
                question="one",
                doc_id="doc-1",
                auth=TEST_AUTH,
                retrieval_fields={"hybrid_enabled": True},
            ),
            answer_question_for_document(
                question="two",
                doc_id="doc-1",
                auth=TEST_AUTH,
                retrieval_fields={"hybrid_enabled": False},
            ),
        )

    assert set(seen) == {True, False}
    assert config.HYBRID_RETRIEVAL_ENABLED is False


@pytest.mark.asyncio
async def test_retrieve_for_documents_does_not_call_answer_generation(pinned_phase3_env, passthrough_docs):
    effective = resolve_retrieval_config({}, RetrievalProcessDefaults.from_process())
    generate = AsyncMock(side_effect=AssertionError("answer generation must not run"))
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=_baseline_chunks())),
        patch("services.chat_service.generate_answer", new=generate),
        patch("services.answer_service.generate_answer", new=generate),
    ):
        result = await retrieve_for_documents(
            "fixed question",
            ["doc-1"],
            "dev",
            effective,
        )

    generate.assert_not_called()
    assert [chunk.id for chunk in result.chunks] == list(PHASE3_ORDER)
    assert result.primary_query == "fixed question"
    assert result.context
    assert "total" in result.timing_ms


@pytest.mark.asyncio
async def test_debug_retrieval_includes_effective_config_and_query(pinned_phase3_env, passthrough_docs):
    find_similar = AsyncMock(return_value=_baseline_chunks())
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with embed_patch, find_patch, answer_patch:
        result = await answer_question_for_document(
            question="fixed question",
            doc_id="doc-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
            retrieval_fields={"hybrid_enabled": True},
        )

    debug = result["retrieval_debug"]
    assert debug["effective_retrieval_query"] == "fixed question"
    assert debug["effective_config"]["hybrid_enabled"] == {"value": True, "source": "request"}
    assert debug["effective_config"]["reranking_enabled"]["source"] == "env"
    assert debug["effective_config"]["max_context_chars"]["source"] == "env"
    assert "timing_ms" in debug


@pytest.mark.asyncio
async def test_compare_style_batch_skips_transform_history_unless_overridden(pinned_phase3_env, passthrough_docs):
    history = [{"role": "user", "content": "earlier topic"}]
    captured: list[list | None] = []

    async def fake_transform(question: str, history=None, **kwargs):
        captured.append(history)
        return QueryTransformResult(queries=[question], original_query=question)

    with (
        patch(
            "services.chat_service.get_embeddings",
            new=AsyncMock(side_effect=lambda texts, **kwargs: [[0.2] for _ in texts]),
        ),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
        patch("services.chat_service.transform_query", new=fake_transform),
        patch("db.get_session_history", new=AsyncMock(return_value=history)),
        patch("db.store_chat_turn", new=AsyncMock()),
    ):
        await answer_questions_for_documents_batch(
            [{"question": "follow up?", "doc_ids": ["doc-1"], "session_id": "sess-1"}],
            auth=TEST_AUTH,
        )
        await answer_questions_for_documents_batch(
            [
                {
                    "question": "follow up?",
                    "doc_ids": ["doc-1"],
                    "session_id": "sess-1",
                    "retrieval_fields": {"skip_history_transform": False},
                }
            ],
            auth=TEST_AUTH,
        )

    assert captured[0] is None
    assert captured[1] == history


@pytest.mark.asyncio
async def test_stream_and_batch_honor_request_hybrid_flag(pinned_phase3_env, passthrough_docs):
    seen: list[bool | None] = []

    async def fake_find(**kwargs):
        seen.append(kwargs.get("hybrid_enabled"))
        return _baseline_chunks()

    async def fake_stream(question, context):
        yield "token"

    provider = AsyncMock()
    provider.model_name = "test-model"
    find_similar = AsyncMock(side_effect=fake_find)
    with (
        patch(
            "services.chat_service.get_embeddings",
            new=AsyncMock(side_effect=lambda texts, **kwargs: [[0.1] for _ in texts]),
        ),
        patch("services.chat_service.find_similar_chunks", new=find_similar),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
        patch("services.chat_service.generate_answer_stream", new=fake_stream),
        patch("services.providers.get_llm_provider", return_value=provider),
    ):
        async for _event in answer_question_stream_for_document(
            "stream q",
            "doc-1",
            auth=TEST_AUTH,
            retrieval_fields={"hybrid_enabled": True},
        ):
            pass
        await answer_questions_for_documents_batch(
            [
                {
                    "question": "batch q",
                    "doc_ids": ["doc-a", "doc-b"],
                    "retrieval_fields": {"hybrid_enabled": False},
                }
            ],
            auth=TEST_AUTH,
        )

    assert True in seen
    assert False in seen


def _cohere_response(results: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"results": results},
        request=httpx.Request("POST", "https://api.cohere.test/v2/rerank"),
    )


@pytest.fixture
def cohere_env(monkeypatch):
    from services.reranker import _reset_reranker_provider

    _reset_reranker_provider()
    monkeypatch.setattr(config, "COHERE_API_KEY", "test-cohere-key")
    monkeypatch.setattr(config, "COHERE_RERANK_MODEL", "rerank-test")
    monkeypatch.setattr(config, "COHERE_RERANK_URL", "https://api.cohere.test/v2/rerank")
    monkeypatch.setattr(config, "RERANKER_TIMEOUT_SEC", 2.0)
    monkeypatch.setattr(config, "RERANKER_MAX_CANDIDATES", 50)
    yield
    _reset_reranker_provider()


_COHERE_FIELDS = {"reranking_enabled": True, "reranker_provider": "cohere"}


@pytest.mark.asyncio
async def test_hosted_reranker_changes_citation_order_vs_similarity(
    pinned_phase3_env, passthrough_docs, cohere_env
):
    chunks = [
        _chunk("lexical", "beta query terms appear here", index=0),
        _chunk("semantic", "an answer without the literal words", index=1),
    ]
    find_similar = AsyncMock(return_value=list(chunks))
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    vendor = [
        {"index": 1, "relevance_score": 0.97},
        {"index": 0, "relevance_score": 0.12},
    ]
    with (
        embed_patch,
        find_patch,
        answer_patch,
        patch.object(httpx.AsyncClient, "post", new=AsyncMock(return_value=_cohere_response(vendor))),
    ):
        similarity = await answer_question_for_document(
            question="beta query",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields={"reranking_enabled": True, "reranker_provider": "similarity"},
        )
        hosted = await answer_question_for_document(
            question="beta query",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields=dict(_COHERE_FIELDS),
        )

    assert [s["chunk_index"] for s in similarity["sources"]] == [0, 1]
    assert [s["chunk_index"] for s in hosted["sources"]] == [1, 0]
    assert [s["rerank_order"] for s in hosted["sources"]] == [1, 2]
    assert hosted["sources"][0]["score_type"] == "reranked"
    assert config.ENABLE_RERANKING is False


@pytest.mark.asyncio
async def test_hosted_reranker_debug_block_when_debug_on(
    pinned_phase3_env, passthrough_docs, cohere_env
):
    chunks = [_chunk("a", "first", index=0), _chunk("b", "second", index=1)]
    find_similar = AsyncMock(return_value=list(chunks))
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    vendor = [
        {"index": 1, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.1},
    ]
    with (
        embed_patch,
        find_patch,
        answer_patch,
        patch.object(httpx.AsyncClient, "post", new=AsyncMock(return_value=_cohere_response(vendor))),
    ):
        debug_on = await answer_question_for_document(
            question="q",
            doc_id="doc-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
            retrieval_fields=dict(_COHERE_FIELDS),
        )
        debug_off = await answer_question_for_document(
            question="q",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields=dict(_COHERE_FIELDS),
        )

    block = debug_on["retrieval_debug"]["reranker"]
    assert block["provider"] == "cohere"
    assert block["model"] == "rerank-test"
    assert block["candidates_sent"] == 2
    assert isinstance(block["latency_ms"], int)
    assert "fallback_reason" not in block
    assert "retrieval_debug" not in debug_off


@pytest.mark.asyncio
async def test_hosted_reranker_failure_keeps_chat_200_with_fallback_reason(
    pinned_phase3_env, passthrough_docs, cohere_env
):
    chunks = [_chunk("a", "first", index=0), _chunk("b", "second", index=1)]
    find_similar = AsyncMock(return_value=list(chunks))
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with (
        embed_patch,
        find_patch,
        answer_patch,
        patch.object(httpx.AsyncClient, "post", new=AsyncMock(side_effect=httpx.ReadTimeout("slow"))),
    ):
        result = await answer_question_for_document(
            question="q",
            doc_id="doc-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
            retrieval_fields=dict(_COHERE_FIELDS),
        )
        quiet = await answer_question_for_document(
            question="q",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields=dict(_COHERE_FIELDS),
        )

    assert "error" not in result
    assert result["answer"] == "ans"
    assert [s["chunk_index"] for s in result["sources"]] == [0, 1]
    assert all(s.get("rerank_order") is None for s in result["sources"])
    assert result["retrieval_debug"]["reranker"]["fallback_reason"] == "timeout"
    assert quiet["answer"] == "ans"
    assert "retrieval_debug" not in quiet


@pytest.mark.asyncio
async def test_reranker_debug_block_absent_when_reranking_not_run(
    pinned_phase3_env, passthrough_docs
):
    find_similar = AsyncMock(return_value=_baseline_chunks())
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with embed_patch, find_patch, answer_patch:
        result = await answer_question_for_document(
            question="q",
            doc_id="doc-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
        )
    assert "reranker" not in result["retrieval_debug"]


def test_request_body_accepts_cohere_provider_but_no_vendor_key_field():
    from pydantic import ValidationError

    from routes.chat import _RETRIEVAL_FIELD_NAMES, ChatRequest, RetrievalOverrides

    request = ChatRequest(
        question="q",
        doc_id=_DOC_ID,
        reranking_enabled=True,
        reranker_provider="cohere",
        reranker_api_key="sk-from-body",
        cohere_api_key="sk-from-body",
        retrieval={"reranker_api_key": "sk-from-body"},
    )
    assert request.reranker_provider == "cohere"
    dumped = request.model_dump()
    assert "sk-from-body" not in str(dumped)
    assert not hasattr(request, "reranker_api_key")
    assert not hasattr(request, "cohere_api_key")
    assert not any("key" in name for name in _RETRIEVAL_FIELD_NAMES)
    assert not any("key" in name for name in RetrievalOverrides.model_fields)
    with pytest.raises(ValidationError):
        ChatRequest(question="q", doc_id=_DOC_ID, reranker_provider="jina")

    effective = resolve_retrieval_config(
        {"reranking_enabled": True, "reranker_provider": "cohere", "reranker_api_key": "sk-from-body"}
    )
    assert effective.reranker_provider == "cohere"
    assert "sk-from-body" not in str(effective.to_debug_dict())


@pytest.fixture
def eval_hybrid_preset():
    reset_retrieval_presets_for_tests()
    set_retrieval_presets_for_tests(
        {
            "eval_hybrid": {
                "hybrid_enabled": True,
                "reranking_enabled": True,
                "reranker_provider": "similarity",
            }
        }
    )
    yield
    reset_retrieval_presets_for_tests()


@pytest.mark.asyncio
async def test_eval_hybrid_preset_enables_hybrid_and_rerank(
    pinned_phase3_env, passthrough_docs, eval_hybrid_preset
):
    vector_chunks = _baseline_chunks()
    hybrid_chunks = [
        _chunk("hybrid-hit", "keyword hit", index=0, score_type=SCORE_TYPE_HYBRID_RRF)
    ]

    async def fake_find(**kwargs):
        if kwargs.get("hybrid_enabled"):
            return hybrid_chunks
        return vector_chunks

    find_similar = AsyncMock(side_effect=fake_find)
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with embed_patch, find_patch, answer_patch:
        result = await answer_question_for_document(
            question="fixed question",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields={"retrieval": {"preset": "eval_hybrid"}},
        )

    assert any(call.kwargs.get("hybrid_enabled") for call in find_similar.await_args_list)
    assert result["sources"][0]["chunk_index"] == 0
    assert result["sources"][0].get("rerank_order") == 1


@pytest.mark.asyncio
async def test_request_override_beats_eval_hybrid_preset(
    pinned_phase3_env, passthrough_docs, eval_hybrid_preset
):
    find_similar = AsyncMock(return_value=_baseline_chunks())
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with embed_patch, find_patch, answer_patch:
        result = await answer_question_for_document(
            question="fixed question",
            doc_id="doc-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
            retrieval_fields={
                "retrieval": {
                    "preset": "eval_hybrid",
                    "hybrid_enabled": False,
                }
            },
        )

    debug = result["retrieval_debug"]
    assert debug["resolved_preset"] == "eval_hybrid"
    assert debug["effective_config"]["hybrid_enabled"] == {"value": False, "source": "request"}
    assert debug["effective_config"]["reranking_enabled"]["source"] == "preset"
    assert not any(call.kwargs.get("hybrid_enabled") for call in find_similar.await_args_list)


@pytest.mark.asyncio
async def test_omitted_preset_keeps_phase3_behavior_matrix(
    pinned_phase3_env, passthrough_docs, eval_hybrid_preset
):
    """Preset map is loaded but omitted on the request; behavior matches Phase 3 baseline."""
    retrieved_ids: list[str] = []

    def recording_sources(chunks):
        retrieved_ids.extend(chunk.id for chunk in chunks)
        return _build_sources(chunks)

    find_similar = AsyncMock(return_value=_baseline_chunks())
    embed_patch, find_patch, answer_patch = _chat_patches(find_similar)
    with (
        embed_patch,
        find_patch,
        answer_patch,
        patch("services.chat_service._build_sources", new=recording_sources),
    ):
        await answer_question_for_document(
            question="fixed question",
            doc_id="doc-1",
            auth=TEST_AUTH,
            retrieval_fields={},
        )

    assert retrieved_ids == list(PHASE3_ORDER)
    assert all("hybrid_enabled" not in call.kwargs for call in find_similar.await_args_list)


@pytest.mark.asyncio
async def test_batch_config_compare_omits_implicit_scope_override(
    pinned_phase3_env, passthrough_docs, eval_hybrid_preset
):
    """Batch items without an explicit scope inherit env/preset, not a phantom request scope."""
    find_similar = AsyncMock(return_value=_baseline_chunks())
    with (
        patch(
            "services.chat_service.get_embeddings",
            new=AsyncMock(side_effect=lambda texts, **kwargs: [[0.1] for _ in texts]),
        ),
        patch("services.chat_service.find_similar_chunks", new=find_similar),
        patch(
            "services.chat_service.build_context_from_chunks",
            return_value="ctx",
        ),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(return_value=("ok", 1, "m")),
        ),
    ):
        results = await answer_questions_for_documents_batch(
            [
                {
                    "question": "q",
                    "doc_ids": ["doc-1"],
                    "match_count": 5,
                    "retrieval_fields": {
                        "hybrid_enabled": True,
                        "retrieval": {"preset": "eval_hybrid"},
                    },
                },
                {
                    "question": "q",
                    "doc_ids": ["doc-1"],
                    "match_count": 5,
                    "retrieval_fields": {"hybrid_enabled": False},
                },
            ],
            auth=TEST_AUTH,
            scope=None,
            debug_retrieval=True,
        )

    scope_a = results[0]["retrieval_debug"]["effective_config"]["scope"]
    scope_b = results[1]["retrieval_debug"]["effective_config"]["scope"]
    assert scope_a["source"] == "env"
    assert scope_b["source"] == "env"


@pytest.mark.asyncio
async def test_batch_config_compare_side_specific_scope_stays_request_sourced(
    pinned_phase3_env, passthrough_docs,
):
    find_similar = AsyncMock(return_value=_baseline_chunks())
    with (
        patch(
            "services.chat_service.get_embeddings",
            new=AsyncMock(side_effect=lambda texts, **kwargs: [[0.1] for _ in texts]),
        ),
        patch("services.chat_service.find_similar_chunks", new=find_similar),
        patch(
            "services.chat_service.build_context_from_chunks",
            return_value="ctx",
        ),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(return_value=("ok", 1, "m")),
        ),
    ):
        results = await answer_questions_for_documents_batch(
            [
                {
                    "question": "q",
                    "doc_ids": ["doc-1"],
                    "match_count": 5,
                    "retrieval_fields": {
                        "hybrid_enabled": True,
                        "scope": "tenant",
                    },
                },
                {
                    "question": "q",
                    "doc_ids": ["doc-1"],
                    "match_count": 5,
                    "retrieval_fields": {"hybrid_enabled": False},
                },
            ],
            auth=TEST_AUTH,
            scope=None,
            debug_retrieval=True,
        )

    assert results[0]["retrieval_debug"]["effective_config"]["scope"] == {
        "value": "tenant",
        "source": "request",
    }
    assert results[1]["retrieval_debug"]["effective_config"]["scope"]["source"] == "env"

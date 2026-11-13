"""Tests for named retrieval configuration presets."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import AuthContext, require_auth
from core.session import Session
from main import invalid_retrieval_config_handler, retrieval_preset_not_found_handler
from middleware.rate_limit import limiter
from routes.chat import router as chat_router
from services.retrieval_config import (
    InvalidRetrievalConfigError,
    RetrievalProcessDefaults,
    merge_retrieval_field_layers,
    resolve_retrieval_config,
)
from services.retrieval_presets import (
    RetrievalPresetNotFoundError,
    RetrievalPresetsLoadError,
    extract_preset_name,
    load_retrieval_presets_from_settings,
    lookup_retrieval_preset,
    reset_retrieval_presets_for_tests,
    set_retrieval_presets_for_tests,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
EVAL_HYBRID_PRESETS_PATH = FIXTURES_DIR / "retrieval_presets_eval_hybrid.json"
EXAMPLE_PRESETS_PATH = Path(__file__).resolve().parent.parent / "retrieval_presets.example.json"


@pytest.fixture(autouse=True)
def _isolated_presets():
    reset_retrieval_presets_for_tests()
    yield
    reset_retrieval_presets_for_tests()


def test_load_fixture_preset_file():
    presets = load_retrieval_presets_from_settings(
        presets_path=str(EVAL_HYBRID_PRESETS_PATH),
        presets_json=None,
    )
    assert presets["eval_hybrid"]["hybrid_enabled"] is True
    assert presets["eval_hybrid"]["reranking_enabled"] is True


def test_repository_example_presets_file_loads_and_merges():
    presets = load_retrieval_presets_from_settings(
        presets_path=str(EXAMPLE_PRESETS_PATH),
        presets_json=None,
    )
    assert set(presets) == {"eval_hybrid", "illustrative_rewrite"}

    env = RetrievalProcessDefaults()
    for name, body in presets.items():
        merged = merge_retrieval_field_layers({"retrieval": {"preset": name}})
        effective = resolve_retrieval_config(
            merged,
            env,
            preset_fields=body,
            resolved_preset=name,
        )
        for field, value in body.items():
            assert getattr(effective, field) == value
            assert effective.sources[field] == "preset"


def test_invalid_preset_file_fails_with_clear_error(tmp_path):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RetrievalPresetsLoadError, match="Invalid JSON"):
        load_retrieval_presets_from_settings(presets_path=str(bad_path), presets_json=None)


def test_invalid_preset_values_fail_at_load(tmp_path):
    bad_path = tmp_path / "invalid_values.json"
    bad_path.write_text(
        '{"broken": {"match_count": 0, "query_transformation_strategy": "bogus"}}',
        encoding="utf-8",
    )
    with pytest.raises(RetrievalPresetsLoadError, match="invalid values"):
        load_retrieval_presets_from_settings(presets_path=str(bad_path), presets_json=None)


def test_invalid_preset_values_fail_when_set_for_tests():
    with pytest.raises(RetrievalPresetsLoadError, match="invalid values"):
        set_retrieval_presets_for_tests({"broken": {"reranker_provider": "jina"}})


def _preset_http_client():
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RetrievalPresetNotFoundError, retrieval_preset_not_found_handler)
    app.add_exception_handler(InvalidRetrievalConfigError, invalid_retrieval_config_handler)
    app.include_router(chat_router)
    app.dependency_overrides[require_auth] = lambda: AuthContext(tenant_id="dev")
    return TestClient(app, raise_server_exceptions=False)


def test_chat_and_stream_unknown_preset_are_400_config_errors():
    set_retrieval_presets_for_tests({})
    payload = {
        "question": "hello",
        "doc_id": "00000000-0000-0000-0000-000000000001",
        "retrieval": {"preset": "missing"},
    }
    with (
        patch("routes.chat.config") as mock_config,
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": "doc", "status": "completed"})),
        patch(
            "routes.chat.get_or_create_session",
            new=AsyncMock(return_value=Session(id="s", tenant_id="dev")),
        ),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch("routes.chat.register_tenant_document"),
    ):
        mock_config.ENABLE_STREAMING = True
        mock_config.RATE_LIMIT_CHAT = "1000/minute"
        with _preset_http_client() as client:
            sync = client.post("/chat", json=payload)
            stream = client.post("/chat/stream", json=payload)

    assert sync.status_code == 400
    assert sync.json()["detail"]["code"] == "preset_not_found"
    assert stream.status_code == 400
    assert stream.json()["detail"]["code"] == "preset_not_found"


def test_invalid_retrieval_config_maps_to_400_not_500():
    set_retrieval_presets_for_tests({"ok": {"hybrid_enabled": True}})
    payload = {
        "question": "hello",
        "doc_id": "00000000-0000-0000-0000-000000000001",
        "retrieval": {"preset": "ok"},
    }
    with (
        patch("routes.chat.config") as mock_config,
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": "doc", "status": "completed"})),
        patch(
            "routes.chat.get_or_create_session",
            new=AsyncMock(return_value=Session(id="s", tenant_id="dev")),
        ),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch("routes.chat.register_tenant_document"),
        patch(
            "routes.chat.resolve_effective_retrieval",
            side_effect=InvalidRetrievalConfigError("Invalid match_count=99."),
        ),
        patch(
            "routes.chat.answer_question_for_document",
            new=AsyncMock(side_effect=InvalidRetrievalConfigError("Invalid match_count=99.")),
        ),
    ):
        mock_config.ENABLE_STREAMING = True
        mock_config.RATE_LIMIT_CHAT = "1000/minute"
        with _preset_http_client() as client:
            sync = client.post("/chat", json=payload)
            stream = client.post("/chat/stream", json=payload)

    assert sync.status_code == 400
    assert sync.json()["detail"]["code"] == "invalid_retrieval_config"
    assert stream.status_code == 400
    assert stream.json()["detail"]["code"] == "invalid_retrieval_config"


def test_unknown_preset_name_raises():
    set_retrieval_presets_for_tests({"known": {"hybrid_enabled": True}})
    with pytest.raises(RetrievalPresetNotFoundError, match="missing"):
        lookup_retrieval_preset("missing")


def test_preset_applies_before_env_and_request_wins():
    set_retrieval_presets_for_tests(
        {"eval_hybrid": {"hybrid_enabled": True, "reranking_enabled": True}}
    )
    env = RetrievalProcessDefaults(hybrid_enabled=False, reranking_enabled=False)
    effective = resolve_retrieval_config(
        {"retrieval": {"preset": "eval_hybrid"}},
        env,
        preset_fields=lookup_retrieval_preset("eval_hybrid"),
        resolved_preset="eval_hybrid",
    )
    assert effective.hybrid_enabled is True
    assert effective.reranking_enabled is True
    assert effective.sources["hybrid_enabled"] == "preset"
    assert effective.resolved_preset == "eval_hybrid"

    overridden = resolve_retrieval_config(
        {"retrieval": {"preset": "eval_hybrid", "hybrid_enabled": False}},
        env,
        preset_fields=lookup_retrieval_preset("eval_hybrid"),
        resolved_preset="eval_hybrid",
    )
    assert overridden.hybrid_enabled is False
    assert overridden.sources["hybrid_enabled"] == "request"
    assert overridden.reranking_enabled is True
    assert overridden.sources["reranking_enabled"] == "preset"


def test_extract_preset_name_prefers_top_level():
    assert extract_preset_name({"preset": "top", "retrieval": {"preset": "nested"}}) == "top"


@pytest.mark.asyncio
async def test_preset_rewrite_changes_effective_query_unless_request_overrides(monkeypatch):
    """A named preset with rewrite must reach transform_query, not only debug state."""
    from unittest.mock import AsyncMock, patch

    from core.auth import AuthContext
    from services.chat_service import answer_question_for_document

    set_retrieval_presets_for_tests(
        {"rewrite_preset": {"query_transformation_strategy": "rewrite"}}
    )
    monkeypatch.setattr("core.config.config.QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr("services.chat_service.config.QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr("services.query_service.config.QUERY_TRANSFORMATION_ENABLED", False)

    async def fake_rewrite(question: str) -> str:
        return f"rewritten:{question}"

    find_similar = AsyncMock(return_value=[])
    with (
        patch("services.query_service.rewrite_query", new=fake_rewrite),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])),
        patch("services.chat_service.find_similar_chunks", new=find_similar),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
    ):
        result = await answer_question_for_document(
            question="original question",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="dev"),
            debug_retrieval=True,
            retrieval_fields={"retrieval": {"preset": "rewrite_preset"}},
        )
        overridden = await answer_question_for_document(
            question="original question",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="dev"),
            debug_retrieval=True,
            retrieval_fields={
                "query_transformation_enabled": False,
                "retrieval": {"preset": "rewrite_preset"},
            },
        )

    assert result["retrieval_debug"]["effective_retrieval_query"] == "rewritten:original question"
    assert result["retrieval_debug"]["effective_config"]["query_transformation_strategy"] == {
        "value": "rewrite",
        "source": "preset",
    }
    assert overridden["retrieval_debug"]["effective_retrieval_query"] == "original question"
    assert overridden["retrieval_debug"]["effective_config"]["query_transformation_enabled"] == {
        "value": False,
        "source": "request",
    }


@pytest.mark.asyncio
async def test_chat_unknown_preset_raises_not_found():
    from unittest.mock import AsyncMock, patch

    from request_utils import make_test_request
    from routes.chat import ChatRequest, RetrievalOverrides, chat

    set_retrieval_presets_for_tests({})
    with (
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": "doc", "status": "completed"})),
        patch("routes.chat.get_or_create_session", new=AsyncMock()),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch("routes.chat.register_tenant_document"),
    ):
        with pytest.raises(RetrievalPresetNotFoundError) as exc_info:
            await chat(
                make_test_request("POST", "/chat"),
                ChatRequest(
                    question="hello",
                    doc_id="00000000-0000-0000-0000-000000000001",
                    retrieval=RetrievalOverrides(preset="eval_hybrid"),
                ),
                auth=__import__("core.auth", fromlist=["AuthContext"]).AuthContext(tenant_id="dev"),
            )
    assert exc_info.value.preset == "eval_hybrid"


@pytest.mark.asyncio
async def test_chat_stream_unknown_preset_raises_before_sse_starts():
    from unittest.mock import AsyncMock, patch

    from core.session import Session
    from request_utils import make_test_request
    from routes.chat import ChatRequest, RetrievalOverrides, chat_stream

    set_retrieval_presets_for_tests({})
    with (
        patch("routes.chat.config") as mock_config,
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": "doc", "status": "completed"})),
        patch(
            "routes.chat.get_or_create_session",
            new=AsyncMock(return_value=Session(id="s", tenant_id="dev")),
        ),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch("routes.chat.register_tenant_document"),
        patch("routes.chat.answer_question_stream_for_document") as stream_fn,
    ):
        mock_config.ENABLE_STREAMING = True
        with pytest.raises(RetrievalPresetNotFoundError) as exc_info:
            await chat_stream(
                make_test_request("POST", "/chat/stream"),
                ChatRequest(
                    question="hello",
                    doc_id="00000000-0000-0000-0000-000000000001",
                    retrieval=RetrievalOverrides(preset="eval_hybrid"),
                ),
                auth=__import__("core.auth", fromlist=["AuthContext"]).AuthContext(tenant_id="dev"),
            )
    assert exc_info.value.preset == "eval_hybrid"
    stream_fn.assert_not_called()


@pytest.mark.asyncio
async def test_stream_service_unknown_preset_emits_sse_error():
    from services.chat_service import answer_question_stream_for_document

    set_retrieval_presets_for_tests({})
    events = [
        event
        async for event in answer_question_stream_for_document(
            question="hello",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="dev"),
            retrieval_fields={"retrieval": {"preset": "missing"}},
        )
    ]
    assert len(events) == 1
    assert events[0].startswith("event: error")
    assert "preset_not_found" in events[0]


def test_batch_unknown_preset_is_400_config_error():
    set_retrieval_presets_for_tests({})
    payload = {
        "queries": [
            {
                "question": "hello",
                "doc_ids": ["00000000-0000-0000-0000-000000000001"],
                "retrieval": {"preset": "missing"},
            }
        ]
    }
    with (
        patch("routes.chat.config") as mock_config,
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": "doc", "status": "completed"})),
        patch(
            "routes.chat.get_or_create_session",
            new=AsyncMock(return_value=Session(id="s", tenant_id="dev")),
        ),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch("routes.chat.register_tenant_document"),
    ):
        mock_config.RATE_LIMIT_CHAT_BATCH = "1000/minute"
        with _preset_http_client() as client:
            response = client.post("/chat/batch", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "preset_not_found"


@pytest.mark.asyncio
async def test_batch_preset_rewrite_changes_effective_query(monkeypatch):
    from services.chat_service import answer_questions_for_documents_batch

    set_retrieval_presets_for_tests(
        {"rewrite_preset": {"query_transformation_strategy": "rewrite"}}
    )
    monkeypatch.setattr("core.config.config.QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr("services.chat_service.config.QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr("services.query_service.config.QUERY_TRANSFORMATION_ENABLED", False)

    async def fake_rewrite(question: str) -> str:
        return f"rewritten:{question}"

    with (
        patch("services.query_service.rewrite_query", new=fake_rewrite),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])),
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
        patch(
            "services.chat_service._resolve_retrieval_doc_ids",
            new=AsyncMock(return_value=["doc-1", "doc-2"]),
        ),
    ):
        results = await answer_questions_for_documents_batch(
            [
                {
                    "question": "original question",
                    "doc_ids": ["doc-1", "doc-2"],
                    "match_count": 5,
                    "retrieval_fields": {"retrieval": {"preset": "rewrite_preset"}},
                }
            ],
            auth=AuthContext(tenant_id="dev"),
            debug_retrieval=True,
        )

    assert results[0]["status"] == "ok"
    assert results[0]["retrieval_debug"]["effective_retrieval_query"] == "rewritten:original question"
    assert results[0]["retrieval_debug"]["effective_config"]["query_transformation_strategy"] == {
        "value": "rewrite",
        "source": "preset",
    }

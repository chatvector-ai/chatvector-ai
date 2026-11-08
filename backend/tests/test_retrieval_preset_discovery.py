"""Tests for GET /retrieval/presets (read-only preset discovery)."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import AuthContext, require_auth
from middleware.rate_limit import limiter
from routes.retrieval import list_retrieval_presets
from request_utils import make_test_request
from routes.retrieval import router as retrieval_router
from services.retrieval_presets import (
    build_retrieval_preset_discovery,
    list_configured_reranker_providers,
    reset_retrieval_presets_for_tests,
    set_retrieval_presets_for_tests,
)


@pytest.fixture(autouse=True)
def _isolated_presets():
    reset_retrieval_presets_for_tests()
    yield
    reset_retrieval_presets_for_tests()


def test_build_discovery_empty_presets_similarity_only():
    set_retrieval_presets_for_tests({})
    payload = build_retrieval_preset_discovery()
    assert payload["preset_names"] == []
    assert payload["reranker_providers"] == ["similarity"]


def test_build_discovery_returns_names_not_bodies():
    set_retrieval_presets_for_tests(
        {
            "eval_hybrid": {
                "hybrid_enabled": True,
                "reranking_enabled": True,
                "reranker_provider": "similarity",
            }
        }
    )
    payload = build_retrieval_preset_discovery()
    assert payload == {
        "preset_names": ["eval_hybrid"],
        "reranker_providers": ["similarity"],
    }
    assert "hybrid_enabled" not in json.dumps(payload)


def test_reranker_providers_includes_cohere_when_key_set(monkeypatch):
    from core import config

    monkeypatch.setattr(config.config, "COHERE_API_KEY", "test-cohere-secret")
    providers = list_configured_reranker_providers()
    assert providers == ["similarity", "cohere"]
    assert "test-cohere-secret" not in json.dumps(providers)


def test_reranker_providers_omits_cohere_without_key(monkeypatch):
    from core import config

    monkeypatch.setattr(config.config, "COHERE_API_KEY", None)
    assert list_configured_reranker_providers() == ["similarity"]


def test_discovery_payload_is_not_a_capabilities_catalog():
    set_retrieval_presets_for_tests({"known": {"hybrid_enabled": True}})
    payload = build_retrieval_preset_discovery()
    forbidden = {
        "llm_provider",
        "embedding_provider",
        "personas",
        "chunk_strategies",
        "graphrag",
        "COHERE_API_KEY",
        "COHERE_RERANK_MODEL",
    }
    for key in forbidden:
        assert key not in payload
    serialized = json.dumps(payload)
    for token in forbidden:
        assert token not in serialized


def _discovery_client():
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(retrieval_router)
    app.dependency_overrides[require_auth] = lambda: AuthContext(tenant_id="dev")
    return TestClient(app, raise_server_exceptions=False)


def test_get_retrieval_presets_route_returns_200():
    set_retrieval_presets_for_tests({"alpha": {"hybrid_enabled": True}, "beta": {}})
    with (
        patch("routes.retrieval.config") as mock_config,
    ):
        mock_config.RATE_LIMIT_DOCUMENT_STATUS = "1000/minute"
        with _discovery_client() as client:
            response = client.get("/retrieval/presets")

    assert response.status_code == 200
    body = response.json()
    assert body["preset_names"] == ["alpha", "beta"]
    assert body["reranker_providers"] == ["similarity"]
    assert "hybrid_enabled" not in response.text


@pytest.mark.asyncio
async def test_list_retrieval_presets_requires_tenant():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await list_retrieval_presets(
            make_test_request("GET", "/retrieval/presets"),
            auth=AuthContext(tenant_id=None),
        )

    assert exc.value.status_code == 401


def test_chat_unknown_preset_still_preset_not_found():
    """Regression: discovery route does not change unknown-preset chat errors."""
    from core.session import Session
    from main import retrieval_preset_not_found_handler
    from routes.chat import router as chat_router
    from services.retrieval_presets import RetrievalPresetNotFoundError

    set_retrieval_presets_for_tests({})
    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RetrievalPresetNotFoundError, retrieval_preset_not_found_handler)
    app.include_router(chat_router)
    app.include_router(retrieval_router)
    app.dependency_overrides[require_auth] = lambda: AuthContext(tenant_id="dev")

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
        patch("routes.retrieval.config") as mock_retrieval_config,
    ):
        mock_config.ENABLE_STREAMING = True
        mock_config.RATE_LIMIT_CHAT = "1000/minute"
        mock_retrieval_config.RATE_LIMIT_DOCUMENT_STATUS = "1000/minute"
        client = TestClient(app, raise_server_exceptions=False)
        discovery = client.get("/retrieval/presets")
        chat = client.post("/chat", json=payload)

    assert discovery.status_code == 200
    assert chat.status_code == 400
    assert chat.json()["detail"]["code"] == "preset_not_found"

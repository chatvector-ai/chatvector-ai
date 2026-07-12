"""Integration tests for tenant-aware API rate limiting (slowapi).

Uses a minimal FastAPI app (upload + chat routers only) so tests do not import
``main`` and trigger DB driver / lifespan side effects at collection time.
"""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from core.auth import AuthContext, require_auth
from core.session import Session
from middleware.rate_limit import get_rate_limit_key, limiter
from routes.chat import router as chat_router
from routes.upload import router as upload_router
from tests.request_utils import make_test_request

_FAKE_SESSION = Session(id="rate-limit-session", tenant_id="dev")


async def _rate_limit_exceeded_handler(
    _request: Request, _exc: RateLimitExceeded
) -> JSONResponse:
    """Mirrors ``main.rate_limit_exceeded_handler`` (tests avoid importing ``main``)."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "code": "rate_limited",
                "message": "Too many requests. Please slow down.",
            }
        },
        headers={"Retry-After": "60"},
    )

# Burst sizes match default Settings when env does not override rate limits.
_UPLOAD_WINDOW = 20
_CHAT_WINDOW = 30

# Valid document ID for POST /chat (Pydantic UUID validation).
_CHAT_DOC_ID = "00000000-0000-0000-0000-000000000001"


def _tenant_auth_from_header(request: Request) -> AuthContext:
    """Test helper: resolve tenant from X-Test-Tenant without API-key parsing."""
    tenant_id = request.headers.get("X-Test-Tenant", "dev")
    request.state.tenant_id = tenant_id
    return AuthContext(tenant_id=tenant_id)


def _rate_limited_test_app(*, tenant_header_auth: bool = False) -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    if tenant_header_auth:
        app.dependency_overrides[require_auth] = _tenant_auth_from_header
    app.include_router(upload_router)
    app.include_router(chat_router)
    return app


@pytest.fixture(autouse=True)
def reset_rate_limit_storage():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(_rate_limited_test_app()) as c:
        yield c


@pytest.fixture
def multi_tenant_client():
    with TestClient(_rate_limited_test_app(tenant_header_auth=True)) as c:
        yield c


def test_post_upload_returns_429_after_limit_exceeded(client):
    files = {"file": ("t.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")}
    with (
        patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
        patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-rl")),
        patch("routes.upload.db.update_document_status", new=AsyncMock()),
        patch("routes.upload.ingestion_queue.enqueue", new=AsyncMock(return_value=1)),
    ):
        for _ in range(_UPLOAD_WINDOW):
            assert client.post("/upload", files=files).status_code == 202
        limited = client.post("/upload", files=files)
    assert limited.status_code == 429


def test_post_chat_returns_429_after_limit_exceeded(client):
    payload = {"question": "hello", "doc_id": _CHAT_DOC_ID, "match_count": 5}
    with (
        patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value={"answer": "ok", "chunks": 0})),
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": _CHAT_DOC_ID})),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
    ):
        for _ in range(_CHAT_WINDOW):
            assert client.post("/chat", json=payload).status_code == 200
        limited = client.post("/chat", json=payload)
    assert limited.status_code == 429


def test_429_response_has_standard_error_shape(client):
    files = {"file": ("x.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")}
    with (
        patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
        patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-x")),
        patch("routes.upload.db.update_document_status", new=AsyncMock()),
        patch("routes.upload.ingestion_queue.enqueue", new=AsyncMock(return_value=1)),
    ):
        for _ in range(_UPLOAD_WINDOW):
            client.post("/upload", files=files)
        resp = client.post("/upload", files=files)
    assert resp.status_code == 429
    body = resp.json()
    assert body["detail"]["code"] == "rate_limited"
    assert "message" in body["detail"]


def test_429_includes_retry_after_header(client):
    payload = {"question": "q", "doc_id": _CHAT_DOC_ID, "match_count": 5}
    with (
        patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value={"answer": "a", "chunks": 0})),
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": _CHAT_DOC_ID})),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
    ):
        for _ in range(_CHAT_WINDOW):
            client.post("/chat", json=payload)
        resp = client.post("/chat", json=payload)
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "60"


def test_two_tenants_sharing_ip_have_separate_buckets(multi_tenant_client):
    """Different tenants behind the same client IP do not share rate-limit buckets."""
    payload = {"question": "hello", "doc_id": _CHAT_DOC_ID, "match_count": 5}
    with (
        patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value={"answer": "ok", "chunks": 0})),
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": _CHAT_DOC_ID})),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
    ):
        for _ in range(_CHAT_WINDOW):
            assert (
                multi_tenant_client.post(
                    "/chat",
                    json=payload,
                    headers={"X-Test-Tenant": "tenant-a"},
                ).status_code
                == 200
            )

        limited_a = multi_tenant_client.post(
            "/chat",
            json=payload,
            headers={"X-Test-Tenant": "tenant-a"},
        )
        still_ok_b = multi_tenant_client.post(
            "/chat",
            json=payload,
            headers={"X-Test-Tenant": "tenant-b"},
        )

    assert limited_a.status_code == 429
    assert still_ok_b.status_code == 200


def test_one_tenant_across_ips_shares_one_bucket(multi_tenant_client):
    """One tenant using multiple client IPs remains in a single rate-limit bucket."""
    payload = {"question": "hello", "doc_id": _CHAT_DOC_ID, "match_count": 5}
    with (
        patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value={"answer": "ok", "chunks": 0})),
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": _CHAT_DOC_ID})),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch(
            "middleware.rate_limit.get_remote_address",
            side_effect=["10.0.0.1", "10.0.0.2", "10.0.0.3"],
        ),
    ):
        for _ in range(_CHAT_WINDOW):
            assert (
                multi_tenant_client.post(
                    "/chat",
                    json=payload,
                    headers={"X-Test-Tenant": "tenant-shared"},
                ).status_code
                == 200
            )

        limited = multi_tenant_client.post(
            "/chat",
            json=payload,
            headers={"X-Test-Tenant": "tenant-shared"},
        )

    assert limited.status_code == 429


def test_endpoint_specific_limits_are_independent(multi_tenant_client):
    """Upload and chat limits apply to separate buckets for the same tenant."""
    files = {"file": ("t.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")}
    payload = {"question": "hello", "doc_id": _CHAT_DOC_ID, "match_count": 5}
    with (
        patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
        patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-rl")),
        patch("routes.upload.db.update_document_status", new=AsyncMock()),
        patch("routes.upload.ingestion_queue.enqueue", new=AsyncMock(return_value=1)),
        patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value={"answer": "ok", "chunks": 0})),
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": _CHAT_DOC_ID})),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
    ):
        for _ in range(_UPLOAD_WINDOW):
            assert (
                multi_tenant_client.post(
                    "/upload",
                    files=files,
                    headers={"X-Test-Tenant": "tenant-limits"},
                ).status_code
                == 202
            )

        upload_limited = multi_tenant_client.post(
            "/upload",
            files=files,
            headers={"X-Test-Tenant": "tenant-limits"},
        )
        chat_ok = multi_tenant_client.post(
            "/chat",
            json=payload,
            headers={"X-Test-Tenant": "tenant-limits"},
        )

    assert upload_limited.status_code == 429
    assert chat_ok.status_code == 200


def test_get_rate_limit_key_uses_tenant_when_present():
    request = make_test_request("POST", "/chat")
    request.state.tenant_id = "tenant-abc"
    assert get_rate_limit_key(request) == "tenant:tenant-abc"


def test_get_rate_limit_key_dev_ip_fallback_when_enabled(monkeypatch):
    monkeypatch.setattr("core.config.config.APP_ENV", "development")
    monkeypatch.setattr("core.config.config.RATE_LIMIT_DEV_IP_FALLBACK", True)
    request = make_test_request("POST", "/chat")
    with patch("middleware.rate_limit.get_remote_address", return_value="203.0.113.9"):
        assert get_rate_limit_key(request) == "ip:203.0.113.9"


def test_get_rate_limit_key_production_does_not_fall_back_to_ip(monkeypatch):
    monkeypatch.setattr("core.config.config.APP_ENV", "production")
    monkeypatch.setattr("core.config.config.RATE_LIMIT_DEV_IP_FALLBACK", True)
    request = make_test_request("POST", "/chat")
    with patch("middleware.rate_limit.get_remote_address", return_value="203.0.113.9"):
        assert get_rate_limit_key(request) == "unauthenticated"


@pytest.mark.asyncio
async def test_require_auth_sets_tenant_on_request_state():
    """require_auth stores tenant_id on request.state for rate-limit keying."""
    from core.auth import require_auth

    request = make_test_request("GET", "/chat")
    result = await require_auth(request)
    assert result.tenant_id == "dev"
    assert request.state.tenant_id == "dev"

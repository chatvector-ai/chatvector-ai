"""Tests for API key authentication and tenant isolation.

Coverage:
  - valid API key → AuthContext populated correctly
  - missing Authorization header (production) → 401
  - malformed Bearer header (production) → 401
  - invalid / unknown API key (production) → 401
  - revoked API key (production) → 401
  - development bypass → returns dev tenant context
  - tenant-scoped document listing (cross-tenant returns 404)
  - cross-tenant document status access → 404
  - cross-tenant document delete → 404
  - cross-tenant chat (retrieval) access → 404
  - cross-tenant session access → 404
"""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.auth import AuthContext, require_auth
from request_utils import make_test_request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request_with_header(header_value: str | None) -> Request:
    """Build a minimal Starlette Request with an optional Authorization header."""
    headers = []
    if header_value is not None:
        headers.append((b"authorization", header_value.encode()))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )


def _make_raw_key(prefix: str = "aabbccdd", secret: str = "testsecret") -> str:
    return f"cv_live_{prefix}.{secret}"


def _make_key_hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# require_auth — development bypass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_auth_dev_bypass_returns_dev_tenant():
    """In test/development APP_ENV, auth is bypassed and the dev tenant is returned."""
    request = _make_request_with_header(None)
    # conftest.py sets APP_ENV=test, so bypass is active
    result = await require_auth(request)
    assert isinstance(result, AuthContext)
    assert result.tenant_id == "dev"


@pytest.mark.asyncio
async def test_require_auth_dev_bypass_respects_dev_tenant_id_env(monkeypatch):
    """DEV_TENANT_ID env var sets the tenant returned during dev bypass."""
    monkeypatch.setenv("DEV_TENANT_ID", "my-dev-tenant")
    request = _make_request_with_header(None)
    result = await require_auth(request)
    assert result.tenant_id == "my-dev-tenant"


# ---------------------------------------------------------------------------
# require_auth — production enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_auth_production_missing_header_returns_401(monkeypatch):
    """Missing Authorization header raises 401 in production mode."""
    monkeypatch.setattr("core.config.config.APP_ENV", "production")
    request = _make_request_with_header(None)

    with pytest.raises(HTTPException) as exc:
        await require_auth(request)

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "missing_credentials"


@pytest.mark.asyncio
async def test_require_auth_production_malformed_scheme_returns_401(monkeypatch):
    """Non-Bearer scheme raises 401 in production mode."""
    monkeypatch.setattr("core.config.config.APP_ENV", "production")
    request = _make_request_with_header("Token abc123")

    with pytest.raises(HTTPException) as exc:
        await require_auth(request)

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "malformed_credentials"


@pytest.mark.asyncio
async def test_require_auth_production_empty_bearer_returns_401(monkeypatch):
    """'Bearer ' with no token raises 401."""
    monkeypatch.setattr("core.config.config.APP_ENV", "production")
    request = _make_request_with_header("Bearer ")

    with pytest.raises(HTTPException) as exc:
        await require_auth(request)

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "malformed_credentials"


@pytest.mark.asyncio
async def test_require_auth_production_invalid_key_returns_401(monkeypatch):
    """An unrecognized API key raises 401 in production mode."""
    monkeypatch.setattr("core.config.config.APP_ENV", "production")
    raw_key = _make_raw_key()
    request = _make_request_with_header(f"Bearer {raw_key}")

    with patch("services.api_key_service.validate_api_key", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await require_auth(request)

    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_require_auth_production_valid_key_returns_auth_context(monkeypatch):
    """A valid API key returns a populated AuthContext in production mode."""
    monkeypatch.setattr("core.config.config.APP_ENV", "production")
    raw_key = _make_raw_key()
    request = _make_request_with_header(f"Bearer {raw_key}")
    fake_tenant_id = "tenant-abc"
    fake_key_id = "key-uuid-123"

    with patch(
        "services.api_key_service.validate_api_key",
        new=AsyncMock(return_value=(fake_tenant_id, fake_key_id)),
    ):
        result = await require_auth(request)

    assert result.tenant_id == fake_tenant_id
    assert result.api_key_id == fake_key_id


# ---------------------------------------------------------------------------
# api_key_service — key generation and validation helpers
# ---------------------------------------------------------------------------


def test_generate_raw_key_format():
    """Generated keys match the expected cv_live_<prefix>.<secret> format."""
    from services.api_key_service import generate_raw_key

    raw_key, prefix, key_hash = generate_raw_key()
    assert raw_key.startswith("cv_live_")
    assert "." in raw_key
    assert raw_key == f"cv_live_{prefix}.{raw_key.split('.', 1)[1]}"
    assert key_hash == hashlib.sha256(raw_key.encode()).hexdigest()


def test_parse_prefix_valid():
    from services.api_key_service import _parse_prefix

    assert _parse_prefix("cv_live_aabbccdd.secret") == "aabbccdd"


def test_parse_prefix_missing_cv_live():
    from services.api_key_service import _parse_prefix

    assert _parse_prefix("sk-notourformat") is None


def test_parse_prefix_no_dot():
    from services.api_key_service import _parse_prefix

    assert _parse_prefix("cv_live_nodotsecret") is None


@pytest.mark.asyncio
async def test_validate_api_key_returns_none_for_unknown_prefix():
    """validate_api_key returns None when no DB row matches the prefix."""
    from services.api_key_service import validate_api_key

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("services.api_key_service._get_session_factory", return_value=mock_factory):
        result = await validate_api_key("cv_live_aabbccdd.somesecret")

    assert result is None


@pytest.mark.asyncio
async def test_validate_api_key_returns_none_for_hash_mismatch():
    """validate_api_key returns None when the hash does not match."""
    from services.api_key_service import validate_api_key

    raw_key = "cv_live_aabbccdd.correctsecret"
    wrong_hash = hashlib.sha256(b"wrong").hexdigest()

    fake_row = MagicMock()
    fake_row.key_hash = wrong_hash
    fake_row.status = "active"
    fake_row.tenant_id = "tenant-x"
    fake_row.id = "key-id-1"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("services.api_key_service._get_session_factory", return_value=mock_factory):
        result = await validate_api_key(raw_key)

    assert result is None


@pytest.mark.asyncio
async def test_validate_api_key_returns_none_for_revoked_key():
    """validate_api_key returns None for keys with status != 'active'."""
    from services.api_key_service import validate_api_key

    raw_key = "cv_live_aabbccdd.correctsecret"
    correct_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    fake_row = MagicMock()
    fake_row.key_hash = correct_hash
    fake_row.status = "revoked"
    fake_row.tenant_id = "tenant-x"
    fake_row.id = "key-id-1"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("services.api_key_service._get_session_factory", return_value=mock_factory):
        result = await validate_api_key(raw_key)

    assert result is None


@pytest.mark.asyncio
async def test_validate_api_key_success():
    """validate_api_key returns (tenant_id, key_id) for a valid active key."""
    from services.api_key_service import validate_api_key

    raw_key = "cv_live_aabbccdd.correctsecret"
    correct_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    fake_row = MagicMock()
    fake_row.key_hash = correct_hash
    fake_row.status = "active"
    fake_row.tenant_id = "tenant-y"
    fake_row.id = "key-id-99"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = fake_row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("services.api_key_service._get_session_factory", return_value=mock_factory):
        result = await validate_api_key(raw_key)

    assert result is not None
    tenant_id, key_id = result
    assert tenant_id == "tenant-y"
    assert key_id == "key-id-99"


# ---------------------------------------------------------------------------
# Tenant isolation — document routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_document_status_returns_404():
    """get_document_status returns 404 when the document belongs to a different tenant."""
    from routes.documents import get_document_status

    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await get_document_status(
                make_test_request("GET", "/documents/doc-other/status"),
                "doc-other",
                auth=AuthContext(tenant_id="tenant-a"),
            )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "document_not_found"


@pytest.mark.asyncio
async def test_cross_tenant_document_delete_returns_404():
    """delete_document returns 404 when the document is not found for the requesting tenant."""
    from routes.documents import delete_document

    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await delete_document(
                make_test_request("DELETE", "/documents/doc-other"),
                "doc-other",
                auth=AuthContext(tenant_id="tenant-a"),
            )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_document_status_tenant_scoped_found():
    """get_document_status succeeds when the document belongs to the requesting tenant."""
    from routes.documents import get_document_status

    payload = {
        "document_id": "doc-mine",
        "status": "completed",
        "chunks": {"total": 5, "processed": 5},
        "error": None,
        "created_at": None,
        "updated_at": None,
    }

    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        result = await get_document_status(
            make_test_request("GET", "/documents/doc-mine/status"),
            "doc-mine",
            auth=AuthContext(tenant_id="tenant-a"),
        )

    assert result["document_id"] == "doc-mine"
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# Tenant isolation — chat routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_chat_returns_404():
    """POST /chat returns 404 when the document does not belong to the requesting tenant."""
    from uuid import UUID

    from routes.chat import chat, ChatRequest

    doc_id = UUID("00000000-0000-0000-0000-000000000001")

    with patch("routes.chat.db.get_document", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await chat(
                make_test_request("POST", "/chat"),
                ChatRequest(question="hello", doc_id=doc_id),
                auth=AuthContext(tenant_id="tenant-a"),
            )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "document_not_found"


# ---------------------------------------------------------------------------
# Tenant isolation — session routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_session_returns_404():
    """get_session returns 404 when the session belongs to a different tenant."""
    from routes.sessions import get_session

    with patch("routes.sessions.session_service.get_session", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as exc:
            await get_session("session-other", auth=AuthContext(tenant_id="tenant-a"))

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_tenant_scoped_session_listing():
    """list_sessions only returns sessions for the authenticated tenant."""
    from routes.sessions import list_sessions, SessionListResponse
    from core.session import Session

    tenant_sessions = [
        Session(id="s1", tenant_id="tenant-a"),
        Session(id="s2", tenant_id="tenant-a"),
    ]

    with patch("routes.sessions.session_service.list_sessions", new=AsyncMock(return_value=tenant_sessions)) as mock_list:
        result = await list_sessions(auth=AuthContext(tenant_id="tenant-a"))

    mock_list.assert_awaited_once_with(tenant_id="tenant-a")
    assert isinstance(result, SessionListResponse)
    assert len(result.sessions) == 2
    assert all(s.tenant_id == "tenant-a" for s in result.sessions)

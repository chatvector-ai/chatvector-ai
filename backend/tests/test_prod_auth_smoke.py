"""Production-mode API authentication smoke tests (issue #387).

Boots the backend with ``APP_ENV=production``, bootstraps a tenant and API
key through the same service used by ``python -m backend.cli
create-tenant-key``, and verifies that authentication enforcement and
tenant isolation work end-to-end against a real PostgreSQL schema — using
real key hashing and validation (no mocking of ``validate_api_key``).

Coverage:
  - Valid Bearer key → populated AuthContext on real DB lookup
  - Missing / malformed / invalid / revoked keys → 401 on protected routes
  - Protected routes accept valid Bearer credentials: upload, document
    status, non-streaming chat, session create/list
  - Cross-tenant denial: tenant A cannot read tenant B document status
    or chat against a tenant B document
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, update
from starlette.requests import Request

pytest.importorskip("pgvector")

from core.auth import require_auth
from core.models import ApiKey, Document, Tenant
from db.sqlalchemy_service import SQLAlchemyService
from services.api_key_service import (
    create_api_key,
    create_tenant,
    reset_session_factory,
)


DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
)


async def _tables_exist() -> bool:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(DB_URL, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema='public' "
                    "AND table_name IN ('tenants','api_keys','documents','sessions')"
                )
            )
            row = result.fetchone()
            return row is not None and row[0] == 4
    except Exception:
        return False
    finally:
        await engine.dispose()


def _check_tables() -> bool:
    try:
        return asyncio.get_event_loop().run_until_complete(_tables_exist())
    except RuntimeError:
        return asyncio.new_event_loop().run_until_complete(_tables_exist())


_TABLES_PRESENT = _check_tables()

_requires_db = pytest.mark.skipif(
    not _TABLES_PRESENT,
    reason="required tables not present — apply migrations first",
)


def _make_request(header_value: str | None) -> Request:
    """Build a minimal Starlette Request with an optional Authorization header."""
    headers: list[tuple[bytes, bytes]] = []
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


def _bearer(raw_key: str) -> str:
    return f"Bearer {raw_key}"


async def _cleanup_tenant(tenant_id: str) -> None:
    svc = SQLAlchemyService()
    async with svc.async_session() as session:
        async with session.begin():
            await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
            await session.execute(delete(Document).where(Document.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))


async def _provision_tenant(prefix: str) -> tuple[str, str, str]:
    """Create a fresh tenant and API key via the real CLI service functions.

    Returns (tenant_id, raw_key, api_key_id).
    """
    tenant_id = f"{prefix}-{uuid4().hex[:10]}"
    tenant = await create_tenant(name=f"Smoke {tenant_id}", tenant_id=tenant_id)
    raw_key, api_key = await create_api_key(tenant_id=tenant.id)
    return tenant.id, raw_key, str(api_key.id)


def _reset_db_singleton() -> None:
    """Null the cached SQLAlchemyService so the next test binds an engine to its own loop.

    pytest-asyncio creates a fresh event loop per test (function scope). The
    ``db.db_service`` singleton caches an async engine bound to the first
    loop that touched it, so subsequent tests reusing the cache hit
    "another operation is in progress" / "event loop is closed" errors.
    Follows the pattern used in ``test_factory.py``.
    """
    import db as db_module

    db_module.db_service = None


@pytest.fixture(autouse=True)
def _production_mode(monkeypatch):
    """Force production authentication semantics for every smoke test."""
    monkeypatch.setattr("core.config.config.APP_ENV", "production")
    reset_session_factory()
    _reset_db_singleton()
    yield
    reset_session_factory()
    _reset_db_singleton()


# ---------------------------------------------------------------------------
# require_auth — production enforcement against a real DB
# ---------------------------------------------------------------------------


@_requires_db
async def test_valid_bearer_key_returns_populated_auth_context():
    tenant_id, raw_key, api_key_id = await _provision_tenant("smoke-valid")
    try:
        result = await require_auth(_make_request(_bearer(raw_key)))
        assert result.tenant_id == tenant_id
        assert result.api_key_id == api_key_id
    finally:
        await _cleanup_tenant(tenant_id)


@_requires_db
async def test_missing_authorization_header_returns_401():
    with pytest.raises(HTTPException) as exc:
        await require_auth(_make_request(None))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "missing_credentials"


@_requires_db
async def test_malformed_authorization_header_returns_401():
    with pytest.raises(HTTPException) as exc:
        await require_auth(_make_request("Token cv_live_deadbeef.secret"))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "malformed_credentials"


@_requires_db
async def test_invalid_bearer_key_returns_401():
    with pytest.raises(HTTPException) as exc:
        await require_auth(_make_request(_bearer("cv_live_deadbeef.notarealsecret")))
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "invalid_api_key"


@_requires_db
async def test_revoked_api_key_returns_401():
    tenant_id, raw_key, _ = await _provision_tenant("smoke-revoked")
    try:
        svc = SQLAlchemyService()
        async with svc.async_session() as session:
            async with session.begin():
                await session.execute(
                    update(ApiKey)
                    .where(ApiKey.tenant_id == tenant_id)
                    .values(status="revoked")
                )

        with pytest.raises(HTTPException) as exc:
            await require_auth(_make_request(_bearer(raw_key)))
        assert exc.value.status_code == 401
        assert exc.value.detail["code"] == "invalid_api_key"
    finally:
        await _cleanup_tenant(tenant_id)


# ---------------------------------------------------------------------------
# Protected routes — valid Bearer succeeds through real auth
# ---------------------------------------------------------------------------


@_requires_db
async def test_upload_route_accepts_valid_bearer():
    from routes.upload import upload

    tenant_id, raw_key, _ = await _provision_tenant("smoke-upload")
    try:
        request = _make_request(_bearer(raw_key))
        auth = await require_auth(request)

        mock_file = AsyncMock(spec=UploadFile)
        mock_file.filename = "smoke.pdf"
        mock_file.content_type = "application/pdf"
        mock_file.read = AsyncMock(return_value=b"fake-pdf-bytes")

        with (
            patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
            patch(
                "routes.upload.ingestion_queue.enqueue",
                new=AsyncMock(return_value=1),
            ) as mock_enqueue,
        ):
            result = await upload(request, mock_file, auth=auth)

        assert result["message"] == "Accepted"
        assert result["status"] == "queued"
        assert result["queue_position"] == 1
        enqueued_job = mock_enqueue.call_args[0][0]
        assert enqueued_job.tenant_id == tenant_id
    finally:
        await _cleanup_tenant(tenant_id)


@_requires_db
async def test_document_status_route_accepts_valid_bearer():
    from routes.documents import get_document_status
    import db

    tenant_id, raw_key, _ = await _provision_tenant("smoke-status")
    try:
        doc_id = await db.create_document("smoke-status.pdf", tenant_id=tenant_id)

        request = _make_request(_bearer(raw_key))
        auth = await require_auth(request)
        result = await get_document_status(request, UUID(doc_id), auth=auth)

        assert result["document_id"] == doc_id
    finally:
        await _cleanup_tenant(tenant_id)


@_requires_db
async def test_chat_route_accepts_valid_bearer_for_owned_document():
    from routes.chat import chat, ChatRequest
    import db

    tenant_id, raw_key, _ = await _provision_tenant("smoke-chat")
    try:
        doc_id = await db.create_document("smoke-chat.pdf", tenant_id=tenant_id)

        request = _make_request(_bearer(raw_key))
        auth = await require_auth(request)

        fake_answer = {
            "answer": "ok",
            "sources": [],
            "session_id": "sess-1",
        }
        with patch(
            "routes.chat.answer_question_for_document",
            new=AsyncMock(return_value=fake_answer),
        ):
            result = await chat(
                request,
                ChatRequest(question="hello?", doc_id=UUID(doc_id)),
                auth=auth,
            )
        assert result == fake_answer
    finally:
        await _cleanup_tenant(tenant_id)


@_requires_db
async def test_session_create_and_list_accept_valid_bearer():
    from routes.sessions import create_session, list_sessions, SessionCreateRequest

    tenant_id, raw_key, _ = await _provision_tenant("smoke-session")
    try:
        request = _make_request(_bearer(raw_key))
        auth = await require_auth(request)

        created = await create_session(SessionCreateRequest(session_id=None), auth=auth)
        assert created.tenant_id == tenant_id

        listing = await list_sessions(auth=auth)
        assert any(s.id == created.id for s in listing.sessions)
        assert all(s.tenant_id == tenant_id for s in listing.sessions)
    finally:
        await _cleanup_tenant(tenant_id)


# ---------------------------------------------------------------------------
# Cross-tenant denial — real DB isolation
# ---------------------------------------------------------------------------


@_requires_db
async def test_cross_tenant_document_status_returns_404():
    from routes.documents import get_document_status
    import db

    tenant_a_id, key_a, _ = await _provision_tenant("smoke-xa")
    tenant_b_id, _, _ = await _provision_tenant("smoke-xb")
    try:
        doc_b_id = await db.create_document("tenant-b.pdf", tenant_id=tenant_b_id)

        request = _make_request(_bearer(key_a))
        auth = await require_auth(request)

        with pytest.raises(HTTPException) as exc:
            await get_document_status(request, UUID(doc_b_id), auth=auth)
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "document_not_found"
    finally:
        await _cleanup_tenant(tenant_a_id)
        await _cleanup_tenant(tenant_b_id)


# ---------------------------------------------------------------------------
# Route-level 401 enforcement — full request path through TestClient
# ---------------------------------------------------------------------------


@_requires_db
def test_sessions_route_rejects_missing_bearer_with_401():
    """GET /sessions without an Authorization header yields 401 at the route layer."""
    from fastapi.testclient import TestClient

    from main import app

    # Bare TestClient (no ``with``) skips app lifespan — we only need the
    # middleware/dependency stack to enforce auth, not the ingestion queue
    # or Redis connection that a production-mode lifespan would require.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/sessions")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "missing_credentials"


@_requires_db
def test_document_status_route_rejects_invalid_bearer_with_401():
    """GET /documents/<uuid>/status with an unknown Bearer key yields 401."""
    from fastapi.testclient import TestClient

    from main import app

    doc_id = uuid4()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        f"/documents/{doc_id}/status",
        headers={"Authorization": "Bearer cv_live_deadbeef.notarealsecret"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_api_key"


@_requires_db
async def test_cross_tenant_chat_returns_404():
    from routes.chat import chat, ChatRequest
    import db

    tenant_a_id, key_a, _ = await _provision_tenant("smoke-ca")
    tenant_b_id, _, _ = await _provision_tenant("smoke-cb")
    try:
        doc_b_id = await db.create_document("tenant-b-chat.pdf", tenant_id=tenant_b_id)

        request = _make_request(_bearer(key_a))
        auth = await require_auth(request)

        with pytest.raises(HTTPException) as exc:
            await chat(
                request,
                ChatRequest(question="leak?", doc_id=UUID(doc_b_id)),
                auth=auth,
            )
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "document_not_found"
    finally:
        await _cleanup_tenant(tenant_a_id)
        await _cleanup_tenant(tenant_b_id)

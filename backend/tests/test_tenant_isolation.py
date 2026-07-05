"""Two-tenant database-backed integration tests for API-key auth and isolation.

These tests use a real PostgreSQL database (the same one pointed at by
DATABASE_URL in conftest.py).  They exercise the full stack — SQLAlchemy
models, api_key_service, and the db module wrappers — with no mocked DB
queries.  Run them via ``make tests`` or ``pytest -v tests/test_tenant_isolation.py``.

Skips gracefully when the schema tables (tenants / api_keys) do not exist, so
the suite does not break environments that have not yet applied migration 005.

Coverage:
  - create_tenant / create_api_key helpers
  - valid real API-key lookup returns (tenant_id, api_key_id)
  - revoked key rejection
  - malformed key rejection
  - tenant-scoped document create / get / status / delete
  - cross-tenant document access returns None (→ 404 at route level)
  - cross-tenant document status returns None
  - cross-tenant document delete skips silently
  - vector retrieval enforces tenant_id at DB level
  - list_tenant_documents returns only own documents
  - DLQEntry carries tenant_id (unit: no DB needed)
  - development bypass via AuthContext (no DB needed)
  - Python SDK sends Authorization header (no DB needed)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# Skip entire module when pgvector is not installed (avoids import errors on
# environments that have not installed all backend dependencies).
pytest.importorskip("pgvector")

from db.sqlalchemy_service import SQLAlchemyService
from db.base import ChunkRecord
from services.api_key_service import (
    _get_session_factory,
    create_api_key,
    create_tenant,
    generate_raw_key,
    reset_session_factory,
    validate_api_key,
)
from core.models import ApiKey, Document, Tenant

# ---------------------------------------------------------------------------
# Module-level skip if DB tables are absent
# ---------------------------------------------------------------------------

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
)


async def _tables_exist() -> bool:
    """Return True only when tenants and api_keys tables are present."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(DB_URL, echo=False)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema='public' "
                    "AND table_name IN ('tenants','api_keys')"
                )
            )
            row = result.fetchone()
            return row is not None and row[0] == 2
    except Exception:
        return False
    finally:
        await engine.dispose()


def _check_tables() -> bool:
    return asyncio.get_event_loop().run_until_complete(_tables_exist())


# Evaluate once at collection time.
_TABLES_PRESENT = _check_tables()

# Applied individually to the DB-backed tests below via @_requires_db.
_requires_db = pytest.mark.skipif(
    not _TABLES_PRESENT,
    reason="tenants/api_keys tables not present — apply 005_api_keys.sql first",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_key_factory():
    """Ensure api_key_service picks up DATABASE_URL changes between tests."""
    reset_session_factory()
    yield
    reset_session_factory()


@pytest.fixture
def svc() -> SQLAlchemyService:
    """SQLAlchemy service pointing at the test database."""
    return SQLAlchemyService()


async def _cleanup_tenant(tenant_id: str, svc: SQLAlchemyService) -> None:
    """Remove test data so tests don't pollute each other.

    Chunks must be deleted before documents (FK from document_chunks.document_id
    → documents.id prevents deleting a document that still has chunks).
    """
    from sqlalchemy import delete, select
    from core.models import ApiKey, Document, DocumentChunk, Tenant

    async with svc.async_session() as session:
        async with session.begin():
            doc_ids = (
                await session.execute(
                    select(Document.id).where(Document.tenant_id == tenant_id)
                )
            ).scalars().all()
            # Delete chunks first to satisfy FK constraint
            for doc_id in doc_ids:
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                )
            for doc_id in doc_ids:
                await session.execute(
                    delete(Document).where(Document.id == doc_id)
                )
            await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_test_tenant_and_key(
    name: str,
    tenant_id: str,
    svc: SQLAlchemyService,
) -> tuple[str, str]:
    """Create tenant + API key, return (raw_key, tenant_id)."""
    await create_tenant(name=name, tenant_id=tenant_id)
    raw_key, _ = await create_api_key(tenant_id=tenant_id)
    return raw_key, tenant_id


def _dummy_embedding(dim: int = 3) -> list[float]:
    return [0.1] * dim


# ---------------------------------------------------------------------------
# API-key validation tests  (real DB)
# ---------------------------------------------------------------------------


@_requires_db
@pytest.mark.asyncio
async def test_valid_api_key_lookup(svc):
    """A freshly created key is validated and returns the correct tenant."""
    tid_a = f"test-tenant-a-{uuid4().hex[:6]}"
    raw_key, _ = await _create_test_tenant_and_key("Tenant A", tid_a, svc)
    try:
        result = await validate_api_key(raw_key)
        assert result is not None
        tenant_id, api_key_id = result
        assert tenant_id == tid_a
        assert api_key_id  # non-empty string
    finally:
        await _cleanup_tenant(tid_a, svc)


@_requires_db
@pytest.mark.asyncio
async def test_revoked_key_rejected(svc):
    """A key whose status is not 'active' must be rejected."""
    from sqlalchemy import update

    tid = f"test-tenant-rev-{uuid4().hex[:6]}"
    raw_key, _ = await _create_test_tenant_and_key("Revoked Tenant", tid, svc)
    try:
        # Revoke the key directly
        async with svc.async_session() as session:
            async with session.begin():
                await session.execute(
                    update(ApiKey)
                    .where(ApiKey.tenant_id == tid)
                    .values(status="revoked")
                )

        result = await validate_api_key(raw_key)
        assert result is None
    finally:
        await _cleanup_tenant(tid, svc)


@pytest.mark.asyncio
async def test_malformed_key_rejected():
    """Keys that don't match the cv_live_ format are rejected without a DB hit."""
    assert await validate_api_key("not-a-key") is None
    assert await validate_api_key("cv_live_") is None
    assert await validate_api_key("cv_live_nodot") is None
    assert await validate_api_key("") is None


# ---------------------------------------------------------------------------
# Tenant-scoped document tests  (real DB)
# ---------------------------------------------------------------------------


@_requires_db
@pytest.mark.asyncio
async def test_cross_tenant_document_access_returns_none(svc):
    """Tenant B cannot fetch a document owned by Tenant A."""
    tid_a = f"test-iso-a-{uuid4().hex[:6]}"
    tid_b = f"test-iso-b-{uuid4().hex[:6]}"

    await create_tenant("Iso A", tid_a)
    await create_tenant("Iso B", tid_b)
    try:
        doc_id = await svc.create_document("secret.pdf", tenant_id=tid_a)

        # Tenant A can read their document
        doc = await svc.get_document(doc_id, tenant_id=tid_a)
        assert doc is not None
        assert doc["tenant_id"] == tid_a

        # Tenant B gets None (same as non-existent)
        cross = await svc.get_document(doc_id, tenant_id=tid_b)
        assert cross is None
    finally:
        await _cleanup_tenant(tid_a, svc)
        await _cleanup_tenant(tid_b, svc)


@_requires_db
@pytest.mark.asyncio
async def test_cross_tenant_document_status_returns_none(svc):
    """Tenant B cannot read status of Tenant A's document."""
    tid_a = f"test-stat-a-{uuid4().hex[:6]}"
    tid_b = f"test-stat-b-{uuid4().hex[:6]}"

    await create_tenant("Stat A", tid_a)
    await create_tenant("Stat B", tid_b)
    try:
        doc_id = await svc.create_document("report.pdf", tenant_id=tid_a)

        # Tenant A sees status
        status_a = await svc.get_document_status(doc_id, tenant_id=tid_a)
        assert status_a is not None

        # Tenant B gets None
        status_b = await svc.get_document_status(doc_id, tenant_id=tid_b)
        assert status_b is None
    finally:
        await _cleanup_tenant(tid_a, svc)
        await _cleanup_tenant(tid_b, svc)


@_requires_db
@pytest.mark.asyncio
async def test_cross_tenant_delete_skips_silently(svc):
    """Tenant B cannot delete Tenant A's document (no error, but doc survives)."""
    tid_a = f"test-del-a-{uuid4().hex[:6]}"
    tid_b = f"test-del-b-{uuid4().hex[:6]}"

    await create_tenant("Del A", tid_a)
    await create_tenant("Del B", tid_b)
    try:
        doc_id = await svc.create_document("contract.pdf", tenant_id=tid_a)

        # Tenant B's delete is a no-op
        await svc.delete_document(doc_id, tenant_id=tid_b)

        # Document still exists for Tenant A
        doc = await svc.get_document(doc_id, tenant_id=tid_a)
        assert doc is not None
    finally:
        await _cleanup_tenant(tid_a, svc)
        await _cleanup_tenant(tid_b, svc)


@_requires_db
@pytest.mark.asyncio
async def test_delete_removes_own_document(svc):
    """A tenant can delete their own document."""
    tid = f"test-owndelete-{uuid4().hex[:6]}"
    await create_tenant("Own Delete", tid)
    try:
        doc_id = await svc.create_document("mine.pdf", tenant_id=tid)
        await svc.delete_document(doc_id, tenant_id=tid)
        doc = await svc.get_document(doc_id, tenant_id=tid)
        assert doc is None
    finally:
        await _cleanup_tenant(tid, svc)


# ---------------------------------------------------------------------------
# list_tenant_documents  (real DB)
# ---------------------------------------------------------------------------


@_requires_db
@pytest.mark.asyncio
async def test_list_tenant_documents_returns_only_own(svc):
    """list_tenant_documents scopes to the requested tenant."""
    tid_a = f"test-list-a-{uuid4().hex[:6]}"
    tid_b = f"test-list-b-{uuid4().hex[:6]}"

    await create_tenant("List A", tid_a)
    await create_tenant("List B", tid_b)
    try:
        doc_a = await svc.create_document("a.pdf", tenant_id=tid_a)
        doc_b = await svc.create_document("b.pdf", tenant_id=tid_b)

        ids_a = await svc.list_tenant_documents(tid_a)
        ids_b = await svc.list_tenant_documents(tid_b)

        assert doc_a in ids_a
        assert doc_b not in ids_a
        assert doc_b in ids_b
        assert doc_a not in ids_b
    finally:
        await _cleanup_tenant(tid_a, svc)
        await _cleanup_tenant(tid_b, svc)


# ---------------------------------------------------------------------------
# Vector retrieval isolation  (real DB, uses embedding vectors)
# ---------------------------------------------------------------------------


@_requires_db
@pytest.mark.asyncio
async def test_vector_retrieval_respects_tenant_isolation(svc):
    """find_similar_chunks with tenant_id does not return chunks from another tenant."""
    from core.config import get_embedding_dim

    dim = get_embedding_dim()
    tid_a = f"test-vr-a-{uuid4().hex[:6]}"
    tid_b = f"test-vr-b-{uuid4().hex[:6]}"

    await create_tenant("VR A", tid_a)
    await create_tenant("VR B", tid_b)
    try:
        doc_a = await svc.create_document("doc_a.txt", tenant_id=tid_a)
        doc_b = await svc.create_document("doc_b.txt", tenant_id=tid_b)

        embedding = [0.01] * dim

        chunk_a = ChunkRecord(
            chunk_text="secret info for tenant A",
            embedding=embedding,
            chunk_index=0,
            character_offset_start=0,
            character_offset_end=20,
        )
        chunk_b = ChunkRecord(
            chunk_text="secret info for tenant B",
            embedding=embedding,
            chunk_index=0,
            character_offset_start=0,
            character_offset_end=20,
        )

        await svc.store_chunks_with_embeddings(doc_a, [chunk_a], tenant_id=tid_a)
        await svc.store_chunks_with_embeddings(doc_b, [chunk_b], tenant_id=tid_b)

        # Tenant A querying doc_a with their own tenant_id returns results
        results_a = await svc.find_similar_chunks(
            doc_id=doc_a, query_embedding=embedding, match_count=5, tenant_id=tid_a
        )
        assert len(results_a) > 0

        # Tenant B querying doc_a (owned by Tenant A) gets nothing — enforced at DB level
        results_cross = await svc.find_similar_chunks(
            doc_id=doc_a, query_embedding=embedding, match_count=5, tenant_id=tid_b
        )
        assert len(results_cross) == 0
    finally:
        await _cleanup_tenant(tid_a, svc)
        await _cleanup_tenant(tid_b, svc)


# ---------------------------------------------------------------------------
# Tenant registry DB fallback  (real DB)
# ---------------------------------------------------------------------------


@_requires_db
@pytest.mark.asyncio
async def test_get_tenant_document_ids_falls_back_to_db(svc):
    """get_tenant_document_ids queries the DB when the in-memory cache is empty."""
    from services.tenant_registry import (
        clear_tenant_registry,
        get_tenant_document_ids,
        register_tenant_document,
    )

    tid = f"test-reg-{uuid4().hex[:6]}"
    await create_tenant("Registry Tenant", tid)
    try:
        doc_id = await svc.create_document("registry.pdf", tenant_id=tid)

        clear_tenant_registry()

        # The in-memory cache is empty; the async function should hit the DB
        with patch("db.list_tenant_documents", new=AsyncMock(return_value=[doc_id])):
            ids = await get_tenant_document_ids(tid)

        assert doc_id in ids
    finally:
        await _cleanup_tenant(tid, svc)


# ---------------------------------------------------------------------------
# DLQ tenant_id field  (unit — no DB needed, no skip guard)
# ---------------------------------------------------------------------------


def test_dlq_entry_carries_tenant_id():
    """DLQEntry stores and preserves tenant_id."""
    from services.queue_base import DLQEntry

    entry = DLQEntry(
        doc_id="d1",
        file_name="x.pdf",
        content_type="application/pdf",
        attempt=1,
        error="oops",
        tenant_id="tenant-x",
    )
    assert entry.tenant_id == "tenant-x"


def test_dlq_entry_no_tenant_id():
    """DLQEntry defaults tenant_id to None for backward compatibility."""
    from services.queue_base import DLQEntry

    entry = DLQEntry(
        doc_id="d1",
        file_name="x.pdf",
        content_type="application/pdf",
        attempt=1,
        error="oops",
    )
    assert entry.tenant_id is None


# ---------------------------------------------------------------------------
# Development bypass  (unit — no DB needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_bypass_returns_dev_tenant(monkeypatch):
    """In development/test mode require_auth returns DEV_TENANT_ID without a key.

    APP_ENV=test is already set by the conftest / Docker environment, so this
    test just verifies that DEV_TENANT_ID is honoured.
    """
    monkeypatch.setenv("DEV_TENANT_ID", "my-dev-tenant")

    from core.auth import require_auth
    from starlette.requests import Request
    import core.config as _cfg_mod

    # Patch APP_ENV on the live config object so require_auth's internal
    # 'from core.config import config' picks up the test value.
    monkeypatch.setattr(_cfg_mod.config, "APP_ENV", "test")

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )

    auth = await require_auth(request)
    assert auth.tenant_id == "my-dev-tenant"


@pytest.mark.asyncio
async def test_production_missing_auth_header_returns_401(monkeypatch):
    """In production mode a missing Authorization header yields 401."""
    from fastapi import HTTPException
    from core.auth import require_auth
    from starlette.requests import Request
    import core.config as _cfg_mod

    monkeypatch.setattr(_cfg_mod.config, "APP_ENV", "production")

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_auth(request)

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Python SDK Authorization header  (unit — no DB needed)
# ---------------------------------------------------------------------------

try:
    from chatvector.client import ChatVectorClient as _ChatVectorClient
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False

_skip_sdk = pytest.mark.skipif(
    not _SDK_AVAILABLE,
    reason="chatvector SDK not installed; install with: pip install ./sdk/python",
)


@_skip_sdk
def test_sdk_sends_authorization_header():
    """ChatVectorClient includes Authorization: Bearer <key> when api_key is set."""
    from chatvector.client import ChatVectorClient

    with ChatVectorClient(
        base_url="http://localhost:8000", api_key="cv_live_aa.bb"
    ) as client:
        assert "Authorization" in client._client.headers
        assert client._client.headers["Authorization"] == "Bearer cv_live_aa.bb"


@_skip_sdk
def test_sdk_no_authorization_header_when_no_key():
    """ChatVectorClient omits Authorization when api_key is not set."""
    from chatvector.client import ChatVectorClient

    with ChatVectorClient(base_url="http://localhost:8000") as client:
        assert "Authorization" not in client._client.headers


# ---------------------------------------------------------------------------
# Session isolation  (unit — in-memory sessions, no DB needed)
# ---------------------------------------------------------------------------


def test_session_isolation_cross_tenant():
    """Tenant B cannot retrieve or delete Tenant A's session."""
    from services.session_service import (
        create_session,
        delete_session,
        get_session,
        list_sessions,
        _SESSIONS,
    )

    _SESSIONS.clear()
    try:
        sess_a = create_session(tenant_id="tenant-a")

        # Tenant B cannot see Tenant A's session
        result = get_session(sess_a.id, tenant_id="tenant-b")
        assert result is None

        # Tenant B's session list does not include Tenant A's session
        sessions_b = list_sessions(tenant_id="tenant-b")
        assert all(s.id != sess_a.id for s in sessions_b)

        # Tenant B's delete attempt does not remove Tenant A's session
        delete_session(sess_a.id, tenant_id="tenant-b")
        still_there = get_session(sess_a.id, tenant_id="tenant-a")
        assert still_there is not None
    finally:
        _SESSIONS.clear()


def test_session_tenant_a_can_access_own_session():
    """Tenant A can read and delete their own session."""
    from services.session_service import (
        create_session,
        delete_session,
        get_session,
        list_sessions,
        _SESSIONS,
    )

    _SESSIONS.clear()
    try:
        sess = create_session(tenant_id="tenant-a")

        result = get_session(sess.id, tenant_id="tenant-a")
        assert result is not None
        assert result.id == sess.id

        sessions = list_sessions(tenant_id="tenant-a")
        assert any(s.id == sess.id for s in sessions)

        delete_session(sess.id, tenant_id="tenant-a")
        gone = get_session(sess.id, tenant_id="tenant-a")
        assert gone is None
    finally:
        _SESSIONS.clear()

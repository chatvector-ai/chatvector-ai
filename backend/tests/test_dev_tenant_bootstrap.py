"""Development tenant bootstrap on startup (issue #335).

Verifies idempotent tenant creation when authentication bypass is active,
production no-op behavior, and document FK safety after bootstrap.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytest.importorskip("pgvector")

from core.models import Tenant
from db.migration_ledger import migration_filenames
from db.sqlalchemy_service import SQLAlchemyService
from services.api_key_service import (
    DevelopmentTenantConfigError,
    bootstrap_development_tenant,
    ensure_tenant_exists,
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
                    "AND table_name IN ('tenants','documents')"
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


_TABLES_PRESENT = _check_tables()

_requires_db = pytest.mark.skipif(
    not _TABLES_PRESENT,
    reason="tenants/documents tables not present — apply migrations first",
)


@pytest.fixture(autouse=True)
def _reset_key_factory():
    reset_session_factory()
    yield
    reset_session_factory()


async def _tenant_exists(tenant_id: str) -> bool:
    from sqlalchemy import select

    svc = SQLAlchemyService()
    async with svc.async_session() as session:
        result = await session.execute(
            select(Tenant.id).where(Tenant.id == tenant_id)
        )
        return result.scalar_one_or_none() is not None


async def _delete_tenant(tenant_id: str) -> None:
    from sqlalchemy import delete

    svc = SQLAlchemyService()
    async with svc.async_session() as session:
        async with session.begin():
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))


async def _delete_tenant_documents(tenant_id: str) -> None:
    from sqlalchemy import delete, select

    from core.models import Document, DocumentChunk

    svc = SQLAlchemyService()
    async with svc.async_session() as session:
        async with session.begin():
            doc_ids = (
                await session.execute(
                    select(Document.id).where(Document.tenant_id == tenant_id)
                )
            ).scalars().all()
            for doc_id in doc_ids:
                await session.execute(
                    delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
                )
            for doc_id in doc_ids:
                await session.execute(
                    delete(Document).where(Document.id == doc_id)
                )
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))


@_requires_db
@pytest.mark.asyncio
async def test_ensure_tenant_exists_creates_when_absent():
    tenant_id = f"bootstrap-create-{uuid4().hex[:8]}"
    try:
        assert not await _tenant_exists(tenant_id)

        created = await ensure_tenant_exists(tenant_id, "Bootstrap Create Test")

        assert created is True
        assert await _tenant_exists(tenant_id)
    finally:
        await _delete_tenant_documents(tenant_id)


@_requires_db
@pytest.mark.asyncio
async def test_ensure_tenant_exists_is_idempotent():
    tenant_id = f"bootstrap-idem-{uuid4().hex[:8]}"
    try:
        first = await ensure_tenant_exists(tenant_id, "Bootstrap Idempotent")
        second = await ensure_tenant_exists(tenant_id, "Bootstrap Idempotent")

        assert first is True
        assert second is False
        assert await _tenant_exists(tenant_id)
    finally:
        await _delete_tenant_documents(tenant_id)


@_requires_db
@pytest.mark.asyncio
async def test_bootstrap_development_tenant_respects_custom_dev_tenant_id(
    monkeypatch,
):
    tenant_id = f"custom-dev-{uuid4().hex[:8]}"
    monkeypatch.setenv("DEV_TENANT_ID", tenant_id)
    try:
        await _delete_tenant(tenant_id)

        await bootstrap_development_tenant("development")

        assert await _tenant_exists(tenant_id)
    finally:
        await _delete_tenant_documents(tenant_id)


@pytest.mark.parametrize("empty_value", ["", "   "])
@pytest.mark.asyncio
async def test_bootstrap_development_tenant_empty_id_fails(monkeypatch, empty_value):
    monkeypatch.setenv("DEV_TENANT_ID", empty_value)

    with pytest.raises(DevelopmentTenantConfigError, match="non-empty"):
        await bootstrap_development_tenant("development")


@pytest.mark.asyncio
async def test_bootstrap_development_tenant_production_noop(monkeypatch):
    tenant_id = f"prod-noop-{uuid4().hex[:8]}"
    monkeypatch.setenv("DEV_TENANT_ID", tenant_id)

    with patch(
        "services.api_key_service.ensure_tenant_exists",
        new_callable=AsyncMock,
    ) as mock_ensure:
        await bootstrap_development_tenant("production")
        mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_fails_when_bootstrap_persistence_fails():
    from fastapi import FastAPI

    from main import lifespan

    app = FastAPI()

    with patch("main.config.APP_ENV", "development"), \
         patch(
             "main._read_migration_ledger_with_retry",
             new_callable=AsyncMock,
             return_value=migration_filenames(),
         ), \
         patch("main.db.fail_stale_documents_global", new_callable=AsyncMock, return_value=set()), \
         patch(
             "services.api_key_service.ensure_tenant_exists",
             new_callable=AsyncMock,
             side_effect=RuntimeError("database unavailable"),
         ), \
         patch("main.ingestion_queue.start", new_callable=AsyncMock), \
         patch("main.ingestion_queue.stop", new_callable=AsyncMock):

        with pytest.raises(RuntimeError, match="database unavailable"):
            async with lifespan(app):
                pass


@_requires_db
@pytest.mark.asyncio
async def test_document_create_after_bootstrap_succeeds(monkeypatch):
    tenant_id = f"bootstrap-doc-{uuid4().hex[:8]}"
    monkeypatch.setenv("DEV_TENANT_ID", tenant_id)
    svc = SQLAlchemyService()
    try:
        await _delete_tenant(tenant_id)
        await bootstrap_development_tenant("development")

        doc_id = await svc.create_document("bootstrap-test.pdf", tenant_id=tenant_id)

        assert doc_id
        doc = await svc.get_document(doc_id, tenant_id=tenant_id)
        assert doc is not None
        assert doc["tenant_id"] == tenant_id
    finally:
        await _delete_tenant_documents(tenant_id)


@_requires_db
@pytest.mark.asyncio
async def test_lifespan_bootstraps_missing_development_tenant(monkeypatch):
    from fastapi import FastAPI

    from main import lifespan

    tenant_id = f"lifespan-boot-{uuid4().hex[:8]}"
    monkeypatch.setenv("DEV_TENANT_ID", tenant_id)
    monkeypatch.setenv("APP_ENV", "development")

    try:
        await _delete_tenant(tenant_id)
        assert not await _tenant_exists(tenant_id)

        app = FastAPI()
        with patch("main.config.APP_ENV", "development"), \
             patch("main.config.QUEUE_BACKEND", "memory"), \
             patch(
                 "main._read_migration_ledger_with_retry",
                 new_callable=AsyncMock,
                 return_value=migration_filenames(),
             ), \
             patch("main.db.fail_stale_documents_global", new_callable=AsyncMock, return_value=set()), \
             patch("main.ingestion_queue.start", new_callable=AsyncMock), \
             patch("main.ingestion_queue.stop", new_callable=AsyncMock):

            async with lifespan(app):
                assert await _tenant_exists(tenant_id)

            assert await _tenant_exists(tenant_id)
    finally:
        await _delete_tenant_documents(tenant_id)

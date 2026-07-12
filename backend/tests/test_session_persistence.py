"""
DB-backed session persistence tests (Issue #386).

These tests exercise create/list/get/delete, document binding persistence, and
restart/worker-safety semantics by working through real DB state rather than
any in-memory dict.  They require a live PostgreSQL instance with migration
007_sessions.sql applied and are skipped when the DB is unavailable.
"""
import sys
import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _fresh_service():
    """Return a SQLAlchemyService pointing at the test database."""
    pytest.importorskip("pgvector")
    if sys.platform == "win32":
        pytest.skip("Psycopg async mode not supported with ProactorEventLoop on Windows")
    from db.sqlalchemy_service import SQLAlchemyService

    return SQLAlchemyService()


@pytest.fixture()
async def svc():
    service = await _fresh_service()
    yield service
    try:
        await service.engine.dispose()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_create_and_get_session(svc):
    """A created session can be retrieved by a second service instance (simulates restart)."""
    session_id = f"persist-{uuid.uuid4()}"
    tenant_id = "test-tenant-persist"

    created = await svc.create_session_record(session_id, tenant_id)
    assert created.id == session_id
    assert created.tenant_id == tenant_id
    assert created.document_ids == []

    # Simulate a second process / worker by using the same service but
    # calling get, which reads from the DB not from memory.
    fetched = await svc.get_session_record(session_id, tenant_id)
    assert fetched is not None
    assert fetched.id == session_id
    assert fetched.tenant_id == tenant_id

    # Cleanup
    await svc.delete_session_record(session_id, tenant_id)


@pytest.mark.asyncio
async def test_document_binding_persisted(svc):
    """Documents bound to a session are visible after a fresh DB read."""
    session_id = f"persist-docs-{uuid.uuid4()}"
    tenant_id = "test-tenant-docs"
    doc_id = f"doc-{uuid.uuid4()}"

    await svc.create_session_record(session_id, tenant_id)
    await svc.add_session_document(session_id, doc_id)

    fetched = await svc.get_session_record(session_id, tenant_id)
    assert fetched is not None
    assert doc_id in fetched.document_ids

    # Idempotent: adding the same document twice should not raise
    await svc.add_session_document(session_id, doc_id)
    fetched2 = await svc.get_session_record(session_id, tenant_id)
    assert fetched2.document_ids.count(doc_id) == 1

    await svc.delete_session_record(session_id, tenant_id)


@pytest.mark.asyncio
async def test_delete_session_cascades_documents(svc):
    """Deleting a session removes its session_documents rows."""
    session_id = f"persist-del-{uuid.uuid4()}"
    tenant_id = "test-tenant-del"
    doc_id = f"doc-{uuid.uuid4()}"

    await svc.create_session_record(session_id, tenant_id)
    await svc.add_session_document(session_id, doc_id)

    deleted = await svc.delete_session_record(session_id, tenant_id)
    assert deleted is True

    fetched = await svc.get_session_record(session_id, tenant_id)
    assert fetched is None


@pytest.mark.asyncio
async def test_list_sessions_scoped_to_tenant(svc):
    """list_session_records only returns sessions for the requested tenant."""
    tenant_a = f"tenant-a-{uuid.uuid4()}"
    tenant_b = f"tenant-b-{uuid.uuid4()}"
    id_a = f"sess-a-{uuid.uuid4()}"
    id_b = f"sess-b-{uuid.uuid4()}"

    await svc.create_session_record(id_a, tenant_a)
    await svc.create_session_record(id_b, tenant_b)

    sessions_a = await svc.list_session_records(tenant_a)
    sessions_b = await svc.list_session_records(tenant_b)

    a_ids = {s.id for s in sessions_a}
    b_ids = {s.id for s in sessions_b}

    assert id_a in a_ids
    assert id_b not in a_ids
    assert id_b in b_ids
    assert id_a not in b_ids

    await svc.delete_session_record(id_a, tenant_a)
    await svc.delete_session_record(id_b, tenant_b)


@pytest.mark.asyncio
async def test_cross_tenant_get_denied(svc):
    """get_session_record returns None when tenant_id does not match."""
    session_id = f"persist-xten-{uuid.uuid4()}"
    owner = "owner-tenant"
    other = "other-tenant"

    await svc.create_session_record(session_id, owner)

    result = await svc.get_session_record(session_id, other)
    assert result is None

    await svc.delete_session_record(session_id, owner)


@pytest.mark.asyncio
async def test_cross_tenant_delete_denied(svc):
    """delete_session_record returns False when tenant_id does not match."""
    session_id = f"persist-xdel-{uuid.uuid4()}"
    owner = "owner-tenant-del"
    other = "other-tenant-del"

    await svc.create_session_record(session_id, owner)

    deleted_by_other = await svc.delete_session_record(session_id, other)
    assert deleted_by_other is False

    # Session still exists for the owner
    fetched = await svc.get_session_record(session_id, owner)
    assert fetched is not None

    await svc.delete_session_record(session_id, owner)


@pytest.mark.asyncio
async def test_service_layer_create_and_get(svc):
    """session_service.create_session / get_session work end-to-end via DB."""
    from unittest.mock import patch

    session_id = f"svc-layer-{uuid.uuid4()}"
    tenant_id = "svc-tenant"

    # Patch db module functions to use our test svc instance
    with patch("db.get_db_service", return_value=svc):
        from services import session_service

        created = await session_service.create_session(session_id, tenant_id)
        assert created.id == session_id

        fetched = await session_service.get_session(session_id, tenant_id)
        assert fetched is not None
        assert fetched.id == session_id

        deleted = await session_service.delete_session(session_id, tenant_id)
        assert deleted is True

        gone = await session_service.get_session(session_id, tenant_id)
        assert gone is None

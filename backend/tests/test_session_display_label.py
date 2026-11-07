"""Computed session display_label (issue 580).

Labels come from the earliest useful user message, then the newest attached
file name, then the exact fallback ``New session``. Listing loads those
sources in bulk rather than once per session.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import event, update

from core.auth import AuthContext
from core.models import ChatMessage, Document

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _fresh_service():
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


async def _add_messages(svc, rows: list[dict]) -> None:
    async with svc.async_session() as session:
        session.add_all(ChatMessage(**row) for row in rows)
        await session.commit()


async def _set_created_at(svc, document_id: str, created_at: datetime) -> None:
    async with svc.async_session() as session:
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(created_at=created_at)
        )
        await session.commit()


def _by_id(sessions):
    return {session.id: session for session in sessions}


async def _ensure_tenant(tenant_id: str) -> None:
    from services.api_key_service import ensure_tenant_exists

    await ensure_tenant_exists(tenant_id, "Session label test")


async def _cleanup(svc, tenant_id: str, session_ids: list[str], document_ids: list[str]) -> None:
    for document_id in document_ids:
        await svc.delete_document(document_id, tenant_id)
    for session_id in session_ids:
        await svc.delete_session_record(session_id, tenant_id)


@pytest.mark.asyncio
async def test_display_label_uses_earliest_nonempty_user_message(svc):
    """A later question and a whitespace-only first message do not win."""
    from routes.sessions import get_session, list_sessions

    tenant_id = f"label-q-{uuid.uuid4()}"
    await _ensure_tenant(tenant_id)
    session_id = f"label-q-sess-{uuid.uuid4()}"
    base = datetime(2026, 3, 1, 12, 0, 0)
    document_id = await svc.create_document("ignored.txt", tenant_id=tenant_id)
    await svc.create_session_record(session_id, tenant_id)
    await svc.add_session_document(session_id, document_id)
    await _add_messages(
        svc,
        [
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "role": "assistant",
                "content": "Hello there",
                "created_at": base,
            },
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "role": "user",
                "content": "  \n\t  ",
                "created_at": base + timedelta(seconds=1),
            },
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "role": "user",
                "content": "Who\napproves   expenses?",
                "created_at": base + timedelta(seconds=2),
            },
            {
                "session_id": session_id,
                "tenant_id": tenant_id,
                "role": "user",
                "content": "What about travel?",
                "created_at": base + timedelta(seconds=3),
            },
        ],
    )

    try:
        with patch("db.get_db_service", return_value=svc):
            listing = await list_sessions(auth=AuthContext(tenant_id=tenant_id))
            fetched = await get_session(session_id, auth=AuthContext(tenant_id=tenant_id))
        assert len(listing.sessions) == 1
        assert listing.sessions[0].display_label == "Who approves expenses?"
        assert fetched.display_label == "Who approves expenses?"
    finally:
        await _cleanup(svc, tenant_id, [session_id], [document_id])


@pytest.mark.asyncio
async def test_display_label_uses_file_name_with_created_at_then_id_tiebreak(svc):
    """Without a useful question, the newest file name wins, then the smaller id."""
    from routes.sessions import list_sessions

    tenant_id = f"label-doc-{uuid.uuid4()}"
    await _ensure_tenant(tenant_id)
    newest_session = f"label-doc-new-{uuid.uuid4()}"
    tie_session = f"label-doc-tie-{uuid.uuid4()}"
    same_time = datetime(2026, 4, 1, 8, 0, 0)
    older_id = await svc.create_document("notes-old.txt", tenant_id=tenant_id)
    newer_id = await svc.create_document("notes.txt", tenant_id=tenant_id)
    tie_a = await svc.create_document("alpha.txt", tenant_id=tenant_id)
    tie_b = await svc.create_document("beta.txt", tenant_id=tenant_id)
    await _set_created_at(svc, older_id, same_time)
    await _set_created_at(svc, newer_id, same_time + timedelta(hours=2))
    await _set_created_at(svc, tie_a, same_time)
    await _set_created_at(svc, tie_b, same_time)

    await svc.create_session_record(newest_session, tenant_id)
    await svc.create_session_record(tie_session, tenant_id)
    await svc.add_session_document(newest_session, older_id)
    await svc.add_session_document(newest_session, newer_id)
    await svc.add_session_document(tie_session, tie_a)
    await svc.add_session_document(tie_session, tie_b)
    await _add_messages(
        svc,
        [
            {
                "session_id": newest_session,
                "tenant_id": tenant_id,
                "role": "user",
                "content": "   \n",
                "created_at": same_time,
            }
        ],
    )

    winner_id = min(tie_a, tie_b)
    winner_name = "alpha.txt" if winner_id == tie_a else "beta.txt"

    try:
        with patch("db.get_db_service", return_value=svc):
            listing = await list_sessions(auth=AuthContext(tenant_id=tenant_id))
        labels = _by_id(listing.sessions)
        assert labels[newest_session].display_label == "notes.txt"
        assert labels[tie_session].display_label == winner_name
    finally:
        await _cleanup(
            svc,
            tenant_id,
            [newest_session, tie_session],
            [older_id, newer_id, tie_a, tie_b],
        )


@pytest.mark.asyncio
async def test_display_label_falls_back_to_new_session(svc):
    """No useful question and no usable file name is exactly ``New session``."""
    from routes.sessions import list_sessions

    tenant_id = f"label-empty-{uuid.uuid4()}"
    await _ensure_tenant(tenant_id)
    empty_session = f"label-empty-sess-{uuid.uuid4()}"
    blank_session = f"label-blank-sess-{uuid.uuid4()}"
    blank_document = await svc.create_document("  \t", tenant_id=tenant_id)
    await svc.create_session_record(empty_session, tenant_id)
    await svc.create_session_record(blank_session, tenant_id)
    await svc.add_session_document(blank_session, blank_document)

    try:
        with patch("db.get_db_service", return_value=svc):
            listing = await list_sessions(auth=AuthContext(tenant_id=tenant_id))
        labels = _by_id(listing.sessions)
        assert labels[empty_session].display_label == "New session"
        assert labels[blank_session].display_label == "New session"
    finally:
        await _cleanup(svc, tenant_id, [empty_session, blank_session], [blank_document])


async def _query_count(svc, tenant_id: str) -> int:
    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(svc.engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        await svc.list_session_records(tenant_id)
    finally:
        event.remove(svc.engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    return len(statements)


@pytest.mark.asyncio
async def test_list_sessions_loads_labels_in_bulk(svc):
    """Message and file-name lookups stay a fixed query count as sessions grow."""
    small_tenant = f"label-bulk-small-{uuid.uuid4()}"
    large_tenant = f"label-bulk-large-{uuid.uuid4()}"
    created: list[tuple[str, str, str]] = []

    async def seed(tenant_id: str, count: int) -> None:
        await _ensure_tenant(tenant_id)
        for index in range(count):
            session_id = f"label-bulk-{index}-{uuid.uuid4()}"
            document_id = await svc.create_document(f"file-{index}.txt", tenant_id=tenant_id)
            await svc.create_session_record(session_id, tenant_id)
            await svc.add_session_document(session_id, document_id)
            await _add_messages(
                svc,
                [
                    {
                        "session_id": session_id,
                        "tenant_id": tenant_id,
                        "role": "user",
                        "content": f"Question {index}",
                        "created_at": datetime(2026, 5, 1, 9, index, 0),
                    }
                ],
            )
            created.append((tenant_id, session_id, document_id))

    await seed(small_tenant, 2)
    await seed(large_tenant, 6)
    try:
        small_count = await _query_count(svc, small_tenant)
        large_count = await _query_count(svc, large_tenant)
        assert small_count == large_count
        assert large_count <= 6
        listed = await svc.list_session_records(large_tenant)
        assert len(listed) == 6
        assert all(session.display_label.startswith("Question ") for session in listed)
    finally:
        for tenant_id, session_id, document_id in created:
            await svc.delete_document(document_id, tenant_id)
            await svc.delete_session_record(session_id, tenant_id)

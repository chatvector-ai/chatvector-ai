"""Phase 3 session/chat correctness tests (Audits #25–#28)."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select

from core.auth import AuthContext
from core.config import get_embedding_dim
from db.base import ChunkRecord
from services.chat_service import (
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
    prepare_batch_chat_items,
    validate_and_normalize_batch_queries,
)
from services.query_service import QueryTransformResult, _format_history_context

TEST_AUTH = AuthContext(tenant_id="phase3-tenant")

pytestmark = pytest.mark.asyncio


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


async def _count_chat_messages(svc, session_id: str, tenant_id: str) -> int:
    from core.models import ChatMessage

    async with svc.async_session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.tenant_id == tenant_id,
            )
        )
        return int(result.scalar_one())


async def _count_session_documents(svc, session_id: str) -> int:
    from core.models import SessionDocument

    async with svc.async_session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(SessionDocument)
            .where(SessionDocument.session_id == session_id)
        )
        return int(result.scalar_one())


async def _count_session_documents_for_doc(svc, document_id: str) -> int:
    from core.models import SessionDocument

    async with svc.async_session() as session:
        result = await session.execute(
            select(func.count())
            .select_from(SessionDocument)
            .where(SessionDocument.document_id == document_id)
        )
        return int(result.scalar_one())


def _mock_transform_result(question: str) -> QueryTransformResult:
    return QueryTransformResult(queries=[question], original_query=question)


# ---------------------------------------------------------------------------
# Session deletion + document cleanup (25.1 / 25.3)
# ---------------------------------------------------------------------------


async def test_delete_session_removes_chat_messages(svc):
    session_id = f"del-msgs-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"

    await svc.create_session_record(session_id, tenant_id)
    await svc.store_chat_turn(session_id, "Q1", "A1", tenant_id)
    assert await _count_chat_messages(svc, session_id, tenant_id) == 2

    deleted = await svc.delete_session_record(session_id, tenant_id)
    assert deleted is True
    assert await _count_chat_messages(svc, session_id, tenant_id) == 0
    assert await svc.get_session_history(session_id, tenant_id) == []


async def test_delete_session_recreate_same_id_empty_history(svc):
    session_id = f"del-recreate-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"

    await svc.create_session_record(session_id, tenant_id)
    await svc.store_chat_turn(session_id, "Q", "A", tenant_id)
    await svc.delete_session_record(session_id, tenant_id)

    await svc.create_session_record(session_id, tenant_id)
    assert await svc.get_session_history(session_id, tenant_id) == []
    assert await _count_chat_messages(svc, session_id, tenant_id) == 0

    await svc.delete_session_record(session_id, tenant_id)


async def test_delete_session_cascades_session_documents_rows(svc):
    session_id = f"persist-del-{uuid.uuid4()}"
    tenant_id = "test-tenant-del"
    doc_id = f"doc-{uuid.uuid4()}"

    await svc.create_session_record(session_id, tenant_id)
    await svc.add_session_document(session_id, doc_id)
    assert await _count_session_documents(svc, session_id) == 1

    deleted = await svc.delete_session_record(session_id, tenant_id)
    assert deleted is True
    assert await _count_session_documents(svc, session_id) == 0
    assert await svc.get_session_record(session_id, tenant_id) is None


async def _ensure_tenant(tenant_id: str) -> None:
    from services.api_key_service import create_tenant

    await create_tenant("Phase 3 test tenant", tenant_id=tenant_id)


async def test_delete_document_unbinds_all_sessions(svc):
    tenant_id = f"tenant-{uuid.uuid4()}"
    await _ensure_tenant(tenant_id)
    doc_id = await svc.create_document(f"file-{uuid.uuid4()}.pdf", tenant_id)
    session_a = f"sess-a-{uuid.uuid4()}"
    session_b = f"sess-b-{uuid.uuid4()}"

    await svc.create_session_record(session_a, tenant_id)
    await svc.create_session_record(session_b, tenant_id)
    await svc.add_session_document(session_a, doc_id)
    await svc.add_session_document(session_b, doc_id)

    await svc.delete_document(doc_id, tenant_id)
    assert await _count_session_documents_for_doc(svc, doc_id) == 0

    fetched_a = await svc.get_session_record(session_a, tenant_id)
    fetched_b = await svc.get_session_record(session_b, tenant_id)
    assert fetched_a is not None and doc_id not in fetched_a.document_ids
    assert fetched_b is not None and doc_id not in fetched_b.document_ids

    await svc.delete_session_record(session_a, tenant_id)
    await svc.delete_session_record(session_b, tenant_id)


async def test_delete_document_failure_does_not_unbind(svc, monkeypatch):
    tenant_id = f"tenant-{uuid.uuid4()}"
    await _ensure_tenant(tenant_id)
    doc_id = await svc.create_document(f"file-{uuid.uuid4()}.pdf", tenant_id)
    session_id = f"sess-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)
    await svc.add_session_document(session_id, doc_id)

    from sqlalchemy.ext.asyncio import AsyncSession

    original_execute = AsyncSession.execute
    unbind_executed = {"done": False}

    async def intercept_execute(self, statement, *args, **kwargs):
        sql_text = str(statement).lower()
        if "session_documents" in sql_text:
            unbind_executed["done"] = True
            return await original_execute(self, statement, *args, **kwargs)
        if unbind_executed["done"] and "documents" in sql_text and "delete" in sql_text:
            raise RuntimeError("simulated delete failure")
        return await original_execute(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", intercept_execute)

    with pytest.raises(RuntimeError):
        await svc.delete_document(doc_id, tenant_id)

    assert await _count_session_documents_for_doc(svc, doc_id) == 1

    monkeypatch.setattr(AsyncSession, "execute", original_execute)
    await svc.delete_session_record(session_id, tenant_id)
    await svc.delete_document(doc_id, tenant_id)


# ---------------------------------------------------------------------------
# Atomic turn persistence (26.4)
# ---------------------------------------------------------------------------


async def test_store_chat_turn_persists_both_messages(svc):
    session_id = f"turn-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)

    await svc.store_chat_turn(session_id, "question", "answer", tenant_id)
    history = await svc.get_session_history(session_id, tenant_id)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"

    await svc.delete_session_record(session_id, tenant_id)


async def test_store_chat_turn_rolls_back_on_failure(svc, monkeypatch):
    session_id = f"turn-fail-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)

    duplicate_id = uuid.uuid4()
    id_iter = iter([duplicate_id, duplicate_id])

    monkeypatch.setattr(
        "db.sqlalchemy_service.uuid.uuid4",
        lambda: next(id_iter),
    )

    with pytest.raises(Exception):
        await svc.store_chat_turn(session_id, "q", "a", tenant_id)

    assert await _count_chat_messages(svc, session_id, tenant_id) == 0
    await svc.delete_session_record(session_id, tenant_id)


async def test_history_ordering_uses_id_tiebreaker(svc):
    session_id = f"order-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)

    fixed_time = datetime.utcnow()
    from core.models import ChatMessage

    user_id = "00000000-0000-0000-0000-000000000001"
    assistant_id = "00000000-0000-0000-0000-000000000002"

    async with svc.async_session() as session:
        session.add(
            ChatMessage(
                id=user_id,
                session_id=session_id,
                tenant_id=tenant_id,
                role="user",
                content="first",
                created_at=fixed_time,
            )
        )
        session.add(
            ChatMessage(
                id=assistant_id,
                session_id=session_id,
                tenant_id=tenant_id,
                role="assistant",
                content="second",
                created_at=fixed_time,
            )
        )
        await session.commit()

    history = await svc.get_session_history(session_id, tenant_id, limit=10)
    assert [msg["content"] for msg in history] == ["first", "second"]
    await svc.delete_session_record(session_id, tenant_id)


# ---------------------------------------------------------------------------
# Concurrency (26.2 / 26.3)
# ---------------------------------------------------------------------------


async def test_get_or_create_session_concurrent(svc):
    from unittest.mock import patch

    session_id = f"concurrent-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"

    with patch("db.get_db_service", return_value=svc):
        from services.session_service import get_or_create_session

        results = await asyncio.gather(
            *[get_or_create_session(session_id, tenant_id) for _ in range(20)]
        )

    assert len({s.id for s in results}) == 1
    assert all(s.id == session_id for s in results)
    await svc.delete_session_record(session_id, tenant_id)


async def test_add_session_document_concurrent_idempotent(svc):
    session_id = f"bind-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"
    doc_id = f"doc-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)

    await asyncio.gather(*[svc.add_session_document(session_id, doc_id) for _ in range(20)])

    assert await _count_session_documents(svc, session_id) == 1
    await svc.delete_session_record(session_id, tenant_id)


# ---------------------------------------------------------------------------
# Explicit POST /sessions cross-tenant probing (Audit 30.1)
# ---------------------------------------------------------------------------


async def test_explicit_create_session_cross_tenant_id_mints_new_id(svc):
    from sqlalchemy import text

    from services.session_service import create_session

    session_id = f"sess-b-{uuid.uuid4().hex[:8]}"
    tenant_b = f"tenant-b-{uuid.uuid4().hex[:8]}"
    tenant_a = f"tenant-a-{uuid.uuid4().hex[:8]}"

    await svc.create_session_record(session_id, tenant_b)
    async with svc.async_session() as session:
        before_active = (
            await session.execute(
                text("SELECT last_active FROM sessions WHERE id = :sid"),
                {"sid": session_id},
            )
        ).scalar_one()

    with patch("db.get_db_service", return_value=svc):
        created = await create_session(session_id, tenant_a)

    assert created.id != session_id
    assert created.tenant_id == tenant_a

    async with svc.async_session() as session:
        after_active = (
            await session.execute(
                text("SELECT last_active FROM sessions WHERE id = :sid"),
                {"sid": session_id},
            )
        ).scalar_one()
    assert after_active == before_active

    await svc.delete_session_record(created.id, tenant_a)
    await svc.delete_session_record(session_id, tenant_b)


async def test_explicit_create_session_same_tenant_duplicate_raises(svc):
    from services.session_service import create_session

    session_id = f"sess-dup-{uuid.uuid4().hex[:8]}"
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"
    await svc.create_session_record(session_id, tenant_id)

    with patch("db.get_db_service", return_value=svc):
        with pytest.raises(ValueError, match="already exists"):
            await create_session(session_id, tenant_id)

    await svc.delete_session_record(session_id, tenant_id)


async def test_explicit_create_session_unused_id_uses_requested_id(svc):
    from services.session_service import create_session

    session_id = f"sess-new-{uuid.uuid4().hex[:8]}"
    tenant_id = f"tenant-{uuid.uuid4().hex[:8]}"

    with patch("db.get_db_service", return_value=svc):
        created = await create_session(session_id, tenant_id)

    assert created.id == session_id
    assert created.tenant_id == tenant_id
    await svc.delete_session_record(session_id, tenant_id)


# ---------------------------------------------------------------------------
# Session listing (25.4)
# ---------------------------------------------------------------------------


async def test_list_sessions_orders_by_last_active_and_id(svc):
    tenant_id = f"tenant-{uuid.uuid4()}"
    older = f"sess-old-{uuid.uuid4()}"
    newer = f"sess-new-{uuid.uuid4()}"
    now = datetime.utcnow()

    async with svc.async_session() as session:
        from core.models import SessionRecord

        session.add(
            SessionRecord(
                id=older,
                tenant_id=tenant_id,
                last_active=now - timedelta(hours=1),
            )
        )
        session.add(
            SessionRecord(
                id=newer,
                tenant_id=tenant_id,
                last_active=now,
            )
        )
        await session.commit()

    listed = await svc.list_session_records(tenant_id)
    ids = [s.id for s in listed if s.id in {older, newer}]
    assert ids == [newer, older]

    await svc.delete_session_record(older, tenant_id)
    await svc.delete_session_record(newer, tenant_id)


async def test_list_sessions_batch_loads_documents_without_n_plus_one(svc):
    tenant_id = f"tenant-{uuid.uuid4()}"
    ids = [f"sess-{i}-{uuid.uuid4()}" for i in range(5)]
    doc_id = f"doc-{uuid.uuid4()}"

    for sid in ids:
        await svc.create_session_record(sid, tenant_id)
        await svc.add_session_document(sid, doc_id)

    call_count = {"n": 0}
    original = svc._load_session_document_ids

    async def counting_loader(db_session, session_id):
        call_count["n"] += 1
        return await original(db_session, session_id)

    with patch.object(svc, "_load_session_document_ids", side_effect=counting_loader):
        listed = await svc.list_session_records(tenant_id)

    assert call_count["n"] == 0
    listed_ids = {s.id for s in listed}
    assert set(ids).issubset(listed_ids)

    for sid in ids:
        await svc.delete_session_record(sid, tenant_id)


# ---------------------------------------------------------------------------
# Batch validation / partial failure (28.x)
# ---------------------------------------------------------------------------


def test_validate_batch_respects_runtime_max_items(monkeypatch):
    monkeypatch.setattr(
        "services.chat_service.config.CHAT_BATCH_MAX_ITEMS",
        25,
        raising=False,
    )
    queries = [{"question": f"q{i}", "doc_ids": ["d1"]} for i in range(25)]
    assert len(validate_and_normalize_batch_queries(queries)) == 25

    with pytest.raises(ValueError, match="CHAT_BATCH_MAX_ITEMS"):
        validate_and_normalize_batch_queries(
            [{"question": f"q{i}", "doc_ids": ["d1"]} for i in range(26)]
        )


@pytest.mark.asyncio
async def test_prepare_batch_invalid_later_item_skips_all_setup():
    tenant_id = "tenant-batch"
    good_doc = "00000000-0000-0000-0000-000000000001"
    missing_doc = "00000000-0000-0000-0000-000000000099"
    raw = [
        {"question": "good", "doc_ids": [good_doc]},
        {"question": "bad", "doc_ids": [missing_doc]},
    ]

    async def fake_get_document(doc_id, tenant_id=tenant_id):
        if doc_id == good_doc:
            return {"id": good_doc}
        return None

    with (
        patch("db.get_document", new=AsyncMock(side_effect=fake_get_document)),
        patch(
            "services.session_service.get_or_create_session",
            new=AsyncMock(),
        ) as mock_create,
        patch(
            "services.session_service.register_session_document",
            new=AsyncMock(),
        ) as mock_bind,
    ):
        service_items, slot_results = await prepare_batch_chat_items(
            raw,
            tenant_id=tenant_id,
            batch_session_id=None,
        )

    assert len(service_items) == 1
    assert slot_results[1] is not None
    assert slot_results[1]["error"]["code"] == "document_not_found"
    mock_create.assert_awaited_once()
    mock_bind.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_embedding_failure_returns_structured_errors():
    with (
        patch(
            "services.chat_service.validate_and_normalize_batch_queries",
            return_value=[{"question": "q", "doc_ids": ["d1"], "match_count": 5, "session_id": "s1", "scope": "session"}],
        ),
        patch("services.chat_service.get_embeddings", new=AsyncMock(side_effect=RuntimeError("embed down"))),
        patch(
            "services.chat_service.transform_query",
            new=AsyncMock(return_value=_mock_transform_result("q")),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
    ):
        results = await answer_questions_for_documents_batch(
            [{"question": "q", "doc_ids": ["d1"], "session_id": "s1"}],
            auth=TEST_AUTH,
        )

    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0]["error"]["code"] == "embedding_failed"


@pytest.mark.asyncio
async def test_single_document_batch_does_not_persist_history():
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
        patch(
            "services.chat_service.transform_query",
            new=AsyncMock(return_value=_mock_transform_result("q")),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=[{"role": "user", "content": "old"}])),
        patch("db.store_chat_turn", new=AsyncMock()) as mock_turn,
    ):
        await answer_questions_for_documents_batch(
            [{"question": "q", "doc_ids": ["doc-1"], "session_id": "sess-1"}],
            auth=TEST_AUTH,
        )

    mock_turn.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_llm_concurrency_bounded(monkeypatch):
    monkeypatch.setattr("services.chat_service.config.CHAT_BATCH_LLM_CONCURRENCY", 2, raising=False)
    import services.chat_service as chat_mod

    chat_mod._batch_llm_limit = 2
    chat_mod._batch_llm_semaphore = asyncio.Semaphore(2)

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def counting_generate(question, context):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        async with lock:
            in_flight -= 1
        return ("ans", 1, "m")

    queries = [
        {"question": f"q{i}", "doc_ids": ["doc-a", "doc-b"], "session_id": f"s{i}"}
        for i in range(6)
    ]

    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]] * 6)),
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-a", "doc-b"])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=counting_generate),
        patch(
            "services.chat_service.transform_query",
            new=AsyncMock(return_value=_mock_transform_result("q")),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch("db.store_chat_turn", new=AsyncMock()),
    ):
        await answer_questions_for_documents_batch(queries, auth=TEST_AUTH)

    assert max_in_flight <= 2


@pytest.mark.asyncio
async def test_batch_llm_semaphore_shared_across_concurrent_requests(monkeypatch):
    """Process-level semaphore: two simultaneous batch calls share the same cap."""
    monkeypatch.setattr("services.chat_service.config.CHAT_BATCH_LLM_CONCURRENCY", 2, raising=False)
    import services.chat_service as chat_mod

    chat_mod._batch_llm_limit = 2
    chat_mod._batch_llm_semaphore = asyncio.Semaphore(2)

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def counting_generate(question, context):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.08)
        async with lock:
            in_flight -= 1
        return ("ans", 1, "m")

    batch = [
        {"question": f"q{i}", "doc_ids": ["doc-a", "doc-b"], "session_id": f"s{i}"}
        for i in range(4)
    ]

    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]] * 4)),
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-a", "doc-b"])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=counting_generate),
        patch(
            "services.chat_service.transform_query",
            new=AsyncMock(return_value=_mock_transform_result("q")),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch("db.store_chat_turn", new=AsyncMock()),
    ):
        await asyncio.gather(
            answer_questions_for_documents_batch(batch, auth=TEST_AUTH),
            answer_questions_for_documents_batch(batch, auth=TEST_AUTH),
        )

    assert max_in_flight <= 2
    assert max_in_flight >= 2


# ---------------------------------------------------------------------------
# Sync chat session_id + streaming persistence (25.2 / 27.x)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_chat_response_includes_session_id():
    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch(
            "services.chat_service.transform_query",
            new=AsyncMock(return_value=_mock_transform_result("q")),
        ),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 0, "m"))),
        patch("db.store_chat_turn", new=AsyncMock()),
    ):
        result = await answer_question_for_document(
            "q",
            "doc-1",
            session_id="sess-sync",
            auth=TEST_AUTH,
        )

    assert result["session_id"] == "sess-sync"


def test_format_history_oldest_to_newest():
    history = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
    rendered = _format_history_context(history)
    assert rendered.index("first") < rendered.index("second") < rendered.index("third")


@pytest.mark.asyncio
async def test_empty_stream_persists_no_response():
    async def empty_stream(q, c):
        if False:
            yield ""

    mock_provider = MagicMock()
    mock_provider.model_name = "test-model"

    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch(
            "services.chat_service.transform_query",
            new=AsyncMock(return_value=_mock_transform_result("q")),
        ),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer_stream", new=empty_stream),
        patch("services.providers.get_llm_provider", return_value=mock_provider),
        patch(
            "db.store_chat_turn",
            new=AsyncMock(return_value=("user-msg", "assistant-msg")),
        ) as mock_turn,
    ):
        events = []
        async for chunk in answer_question_stream_for_document(
            "q",
            "doc-1",
            session_id="sess-empty",
            auth=TEST_AUTH,
        ):
            events.append(chunk)

    assert any("complete" in e for e in events)
    assert any("done" in e for e in events)
    mock_turn.assert_awaited_once()
    assert mock_turn.await_args.kwargs["answer"] == "No response."


@pytest.mark.asyncio
async def test_stream_tokens_then_error_persists_nothing():
    from services.answer_service import LLM_MSG_RATE_LIMIT

    async def token_then_error(q, c):
        yield "part1"
        yield "part2"
        yield LLM_MSG_RATE_LIMIT

    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch(
            "services.chat_service.transform_query",
            new=AsyncMock(return_value=_mock_transform_result("q")),
        ),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer_stream", new=token_then_error),
        patch("db.store_chat_turn", new=AsyncMock()) as mock_turn,
    ):
        events = []
        async for chunk in answer_question_stream_for_document(
            "q",
            "doc-1",
            session_id="sess-err",
            auth=TEST_AUTH,
        ):
            events.append(chunk)

    token_events = [e for e in events if e.startswith("event: token")]
    assert len(token_events) == 2
    assert not any("complete" in e for e in events)
    assert not any("done" in e for e in events)
    mock_turn.assert_not_awaited()

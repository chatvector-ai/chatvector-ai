"""Tests for migration 018: chat_messages.sources JSONB snapshot column."""

from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "db" / "init" / "018_chat_message_sources.sql"
)
MIGRATION_FILENAME = "018_chat_message_sources.sql"


def _executable_sql() -> str:
    return "\n".join(
        line
        for line in MIGRATION_PATH.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ).strip()


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_migration_is_atomic_and_self_records():
    sql = _executable_sql()
    assert re.match(r"BEGIN\s*;", sql, re.IGNORECASE)
    assert MIGRATION_FILENAME in sql
    assert re.search(
        r"ON\s+CONFLICT\s*\(\s*filename\s*\)\s+DO\s+NOTHING\s*;"
        r"\s*COMMIT\s*;\s*$",
        sql,
        re.IGNORECASE,
    )


def test_migration_adds_nullable_sources_without_default_or_index():
    sql = _executable_sql()
    assert re.search(
        r"ALTER\s+TABLE\s+chat_messages\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+sources\s+JSONB\s*;",
        sql,
        re.IGNORECASE,
    )
    assert re.search(r"\bDEFAULT\b", sql, re.IGNORECASE) is None
    assert re.search(r"\bINDEX\b", sql, re.IGNORECASE) is None
    assert re.search(r"\bUPDATE\b", sql, re.IGNORECASE) is None


def test_orm_chat_message_declares_nullable_sources():
    from core.models import ChatMessage

    column = ChatMessage.__table__.columns["sources"]
    assert column.nullable is True
    assert column.default is None
    assert column.server_default is None


@pytest.fixture
def postgres_connection():
    psycopg = pytest.importorskip("psycopg")
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
    )
    dsn = re.sub(r"^postgresql\+(?:asyncpg|psycopg)://", "postgresql://", database_url)

    try:
        connection = psycopg.connect(dsn, connect_timeout=2)
    except psycopg.OperationalError as exc:
        if os.getenv("CI", "").strip().lower() in {"1", "true", "yes"}:
            pytest.fail(f"PostgreSQL is required for migration tests in CI: {exc}")
        pytest.skip(f"PostgreSQL is unavailable: {exc}")

    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_018_is_idempotent_and_leaves_existing_rows_null(postgres_connection):
    conn = postgres_connection
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    session_id = f"test-018-{uuid4().hex[:8]}"
    message_id = str(uuid4())

    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.schema_migrations')")
            if cur.fetchone()[0] is None:
                pytest.skip("schema_migrations is not installed")

            cur.execute("SELECT to_regclass('public.chat_messages')")
            if cur.fetchone()[0] is None:
                pytest.skip("chat_messages is not installed")

            cur.execute(migration_sql)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(migration_sql)
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM public.schema_migrations WHERE filename = %s",
                (MIGRATION_FILENAME,),
            )
            assert cur.fetchone()[0] == 1

            cur.execute(
                "SELECT is_nullable, data_type, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'chat_messages' "
                "AND column_name = 'sources'"
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] == "YES"
            assert row[1] == "jsonb"
            assert row[2] is None

            cur.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'chat_messages' AND indexdef ILIKE %s",
                ("%sources%",),
            )
            assert cur.fetchall() == []

            cur.execute(
                "INSERT INTO chat_messages (id, session_id, role, content) "
                "VALUES (%s, %s, 'assistant', 'pre-snapshot') RETURNING sources",
                (message_id, session_id),
            )
            assert cur.fetchone()[0] is None
        conn.rollback()
    finally:
        conn.rollback()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chat_messages WHERE id = %s", (message_id,))
            conn.commit()
        except Exception:
            conn.rollback()

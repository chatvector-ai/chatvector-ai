"""Unit tests for isolated pytest database bootstrap."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from db.ensure_test_database import (
    admin_database_url,
    default_test_database_name,
    ensure_test_database,
    init_sql_files,
    target_database_url,
    to_sync_postgres_url,
)


def test_to_sync_postgres_url_strips_sqlalchemy_driver():
    assert (
        to_sync_postgres_url("postgresql+asyncpg://postgres:pw@db:5432/postgres")
        == "postgresql://postgres:pw@db:5432/postgres"
    )


def test_admin_database_url_replaces_db_name_with_postgres(monkeypatch):
    monkeypatch.delenv("DATABASE_ADMIN_URL", raising=False)
    url = admin_database_url(
        "postgresql+asyncpg://postgres:secret@localhost:5432/chatvector_test"
    )
    assert url == "postgresql://postgres:secret@localhost:5432/postgres"


def test_target_database_url_sets_target_db():
    admin = "postgresql://postgres:secret@db:5432/postgres"
    assert target_database_url(admin, "chatvector_test") == (
        "postgresql://postgres:secret@db:5432/chatvector_test"
    )


def test_init_sql_files_sorted_lexically(tmp_path: Path):
    (tmp_path / "010_b.sql").write_text("-- b", encoding="utf-8")
    (tmp_path / "002_a.sql").write_text("-- a", encoding="utf-8")
    names = [path.name for path in init_sql_files(tmp_path)]
    assert names == ["002_a.sql", "010_b.sql"]


def test_default_test_database_name_reads_env(monkeypatch):
    monkeypatch.setenv("CHATVECTOR_TEST_DATABASE", "custom_test_db")
    assert default_test_database_name() == "custom_test_db"


def test_ensure_test_database_creates_isolated_database():
    if os.getenv("SKIP_DB_INTEGRATION"):
        pytest.skip("SKIP_DB_INTEGRATION is set")

    import psycopg

    admin = os.getenv(
        "DATABASE_ADMIN_URL",
        "postgresql://postgres:postgres@localhost:5432/postgres",
    )
    db_name = f"ensure_test_{uuid.uuid4().hex[:10]}"

    from db.ensure_test_database import _connection_params

    try:
        with psycopg.connect(
            **_connection_params(admin, database="postgres"),
        ):
            pass
    except psycopg.Error:
        pytest.skip("Postgres not available for ensure_test_database integration test")

    try:
        created_url = ensure_test_database(admin_url=admin, database_name=db_name)
        assert created_url.endswith(f"/{db_name}")

        # Idempotent second call should not fail.
        ensure_test_database(admin_url=admin, database_name=db_name)
    finally:
        from urllib.parse import urlparse

        parsed = urlparse(admin)
        with psycopg.connect(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            user=parsed.username or "postgres",
            password=parsed.password or "",
            dbname="postgres",
            autocommit=True,
        ) as conn:
            conn.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (db_name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
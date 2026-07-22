"""Migration ledger schema, backfill, and startup drift detection tests."""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from db.migration_ledger import (
    BASELINE_MIGRATION_FILENAMES,
    LEDGER_BOOTSTRAP_FILENAME,
    MigrationDriftError,
    MigrationFilesMissingError,
    MigrationLedgerMissingError,
    MigrationLedgerSchemaError,
    compare_migration_filenames,
    migration_filenames,
    validate_migration_ledger,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BACKEND_DIR / "db" / "init"
LEDGER_MIGRATION = MIGRATIONS_DIR / LEDGER_BOOTSTRAP_FILENAME


@pytest.fixture(scope="module")
def ledger_sql() -> str:
    return LEDGER_MIGRATION.read_text(encoding="utf-8")


def _sql_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda path: path.name)


def _recorded_filenames(sql: str) -> list[str]:
    return re.findall(r"\('([0-9]{3}_[^']+\.sql)'\)", sql)


def _write_migration_bundle(directory: Path, *extra_filenames: str) -> None:
    for filename in (*BASELINE_MIGRATION_FILENAMES, *extra_filenames):
        (directory / filename).write_text("-- test\n", encoding="utf-8")


def _valid_ledger_schema() -> dict[str, bool]:
    return {
        "is_table": True,
        "has_only_expected_columns": True,
        "filename_is_text_not_null": True,
        "filename_is_primary_key": True,
        "applied_at_is_timestamptz_not_null": True,
        "applied_at_default_is_now": True,
    }


def _mapping_result(value):
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = value
    return result


def test_ledger_schema_contract(ledger_sql):
    assert re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+public\.schema_migrations\s*\("
        r"\s*filename\s+TEXT\s+PRIMARY\s+KEY\s*,"
        r"\s*applied_at\s+TIMESTAMPTZ\s+NOT\s+NULL\s+DEFAULT\s+now\(\)\s*\)",
        ledger_sql,
        re.IGNORECASE | re.DOTALL,
    )


def test_ledger_backfill_matches_runtime_baseline(ledger_sql):
    assert _recorded_filenames(ledger_sql) == list(BASELINE_MIGRATION_FILENAMES)


def test_ledger_creation_and_backfill_are_atomic(ledger_sql):
    executable_sql = "\n".join(
        line
        for line in ledger_sql.splitlines()
        if not line.lstrip().startswith("--")
    ).strip()

    assert re.match(r"BEGIN\s*;", executable_sql, re.IGNORECASE)
    assert re.search(r"COMMIT\s*;\s*$", executable_sql, re.IGNORECASE)


def test_all_migration_files_are_recorded_exactly_once():
    sql_files = _sql_files()
    recorded = [
        filename
        for sql_file in sql_files
        for filename in _recorded_filenames(sql_file.read_text(encoding="utf-8"))
    ]

    assert sorted(recorded) == [path.name for path in sql_files]
    assert all(count == 1 for count in Counter(recorded).values())


def test_ledger_and_future_migrations_self_record_before_commit():
    for sql_file in _sql_files():
        if sql_file.name < LEDGER_BOOTSTRAP_FILENAME:
            continue
        executable_sql = "\n".join(
            line
            for line in sql_file.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("--")
        ).strip()

        assert sql_file.name in _recorded_filenames(executable_sql)
        assert re.match(r"BEGIN\s*;", executable_sql, re.IGNORECASE)
        assert re.search(
            r"ON\s+CONFLICT\s*\(\s*filename\s*\)\s+DO\s+NOTHING\s*;"
            r"\s*COMMIT\s*;\s*$",
            executable_sql,
            re.IGNORECASE,
        )


def test_migration_discovery_is_lexically_sorted(tmp_path):
    for filename in ("010_last.sql", "004_hybrid.sql", "004_chat.sql"):
        (tmp_path / filename).write_text("-- test\n", encoding="utf-8")
    (tmp_path / "README.txt").write_text("ignored\n", encoding="utf-8")

    assert migration_filenames(tmp_path) == (
        "004_chat.sql",
        "004_hybrid.sql",
        "010_last.sql",
    )


def test_compare_preserves_both_duplicate_prefix_files():
    drift = compare_migration_filenames(
        ("004_chat_history.sql", "004_hybrid_retrieval.sql"),
        ("004_chat_history.sql",),
    )

    assert drift.missing_from_ledger == ("004_hybrid_retrieval.sql",)


def test_missing_ledger_has_operator_facing_bootstrap_message():
    with pytest.raises(MigrationLedgerMissingError) as exc_info:
        validate_migration_ledger(None)

    message = str(exc_info.value)
    assert LEDGER_BOOTSTRAP_FILENAME in message
    assert "psql -v ON_ERROR_STOP=1 -f <migration-file>" in message
    assert "DEVELOPMENT.md#upgrading-an-existing-database" in message


def test_incomplete_application_migration_bundle_is_fatal(tmp_path):
    (tmp_path / LEDGER_BOOTSTRAP_FILENAME).write_text("-- test\n", encoding="utf-8")

    with pytest.raises(MigrationFilesMissingError, match="001_init.sql"):
        validate_migration_ledger(BASELINE_MIGRATION_FILENAMES, tmp_path)


def test_missing_migration_has_operator_facing_drift_message(tmp_path):
    _write_migration_bundle(tmp_path, "009_example.sql")

    with pytest.raises(MigrationDriftError) as exc_info:
        validate_migration_ledger(BASELINE_MIGRATION_FILENAMES, tmp_path)

    message = str(exc_info.value)
    assert "009_example.sql" in message
    assert "psql -v ON_ERROR_STOP=1 -f <migration-file>" in message
    assert "post-ledger migration files" in message
    assert "each file must record its own ledger row" in message
    assert "Do not replay 001_init.sql" in message


def test_missing_historical_row_requires_verification_and_baseline_rerun(tmp_path):
    _write_migration_bundle(tmp_path)
    applied = tuple(
        filename
        for filename in BASELINE_MIGRATION_FILENAMES
        if filename != "007_sessions.sql"
    )

    with pytest.raises(MigrationDriftError) as exc_info:
        validate_migration_ledger(applied, tmp_path)

    message = str(exc_info.value)
    assert "007_sessions.sql" in message
    assert "do not prove that their historical SQL is unapplied" in message
    assert "Verify each migration's schema effects or deployment history" in message
    assert "rerun 008_schema_migrations.sql" in message
    assert "Do not replay 001_init.sql" in message


def test_missing_bootstrap_row_requires_idempotent_baseline_rerun(tmp_path):
    _write_migration_bundle(tmp_path)
    applied = tuple(
        filename
        for filename in BASELINE_MIGRATION_FILENAMES
        if filename != LEDGER_BOOTSTRAP_FILENAME
    )

    with pytest.raises(MigrationDriftError) as exc_info:
        validate_migration_ledger(applied, tmp_path)

    message = str(exc_info.value)
    assert "Rerun 008_schema_migrations.sql" in message
    assert "restore its idempotent baseline ledger rows" in message


def test_missing_bootstrap_and_future_migration_reports_repair_order(tmp_path):
    _write_migration_bundle(tmp_path, "009_example.sql")
    applied = tuple(
        filename
        for filename in BASELINE_MIGRATION_FILENAMES
        if filename != LEDGER_BOOTSTRAP_FILENAME
    )

    with pytest.raises(MigrationDriftError) as exc_info:
        validate_migration_ledger(applied, tmp_path)

    message = str(exc_info.value)
    assert message.index("Rerun 008_schema_migrations.sql") < message.index(
        "Apply the missing post-ledger migration files"
    )


def test_mixed_baseline_and_future_drift_reports_repair_order(tmp_path):
    _write_migration_bundle(tmp_path, "009_example.sql")
    applied = tuple(
        filename
        for filename in BASELINE_MIGRATION_FILENAMES
        if filename != "007_sessions.sql"
    )

    with pytest.raises(MigrationDriftError) as exc_info:
        validate_migration_ledger(applied, tmp_path)

    message = str(exc_info.value)
    assert "007_sessions.sql" in message
    assert "009_example.sql" in message
    assert message.index("rerun 008_schema_migrations.sql") < message.index(
        "Apply the missing post-ledger migration files"
    )


def test_database_newer_than_checkout_is_advisory(tmp_path):
    _write_migration_bundle(tmp_path)

    drift = validate_migration_ledger(
        (*BASELINE_MIGRATION_FILENAMES, "009_future.sql"), tmp_path
    )

    assert drift.missing_from_ledger == ()
    assert drift.unknown_to_checkout == ("009_future.sql",)


@pytest.mark.asyncio
async def test_startup_stops_before_database_work_and_logs_missing_filename():
    from fastapi import FastAPI

    from main import lifespan

    applied = tuple(
        filename
        for filename in migration_filenames()
        if filename != "007_sessions.sql"
    )
    stale_reset = AsyncMock(return_value=set())
    operator_log = MagicMock()

    with (
        patch(
            "main._read_migration_ledger_with_retry",
            new_callable=AsyncMock,
            return_value=applied,
        ),
        patch("main.db.fail_stale_documents_global", stale_reset),
        patch("main._log_operator_issue", operator_log),
    ):
        with pytest.raises(MigrationDriftError, match="007_sessions.sql"):
            async with lifespan(FastAPI()):
                pass

    stale_reset.assert_not_awaited()
    operator_log.assert_called_once()
    operator_message = operator_log.call_args.args[1]
    assert "007_sessions.sql" in operator_message
    assert "rerun 008_schema_migrations.sql" in operator_message


def test_operator_issue_is_written_to_app_and_console_logs():
    import main

    with patch.object(main.logger, "log") as app_log, patch.object(
        main.operator_logger, "log"
    ) as console_log:
        main._log_operator_issue(40, "migration drift")

    app_log.assert_called_once_with(40, "%s", "migration drift")
    console_log.assert_called_once_with(40, "%s", "migration drift")


@pytest.mark.asyncio
async def test_startup_retry_waits_for_in_progress_ledger_insert():
    import main

    incomplete = tuple(
        filename
        for filename in migration_filenames()
        if filename != LEDGER_BOOTSTRAP_FILENAME
    )
    current = migration_filenames()
    ledger_read = AsyncMock(side_effect=(incomplete, current))
    retry_sleep = AsyncMock()

    with patch("main.db.list_applied_migrations", ledger_read), patch(
        "main.asyncio.sleep", retry_sleep
    ):
        result = await main._read_migration_ledger_with_retry()

    assert result == current
    assert ledger_read.await_count == 2
    retry_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_ledger_read_has_a_per_attempt_timeout():
    import asyncio

    import main

    async def never_finishes():
        await asyncio.Event().wait()

    with patch.object(main, "MIGRATION_LEDGER_STARTUP_ATTEMPTS", 1), patch.object(
        main, "MIGRATION_LEDGER_READ_TIMEOUT_SECONDS", 0.01
    ), patch("main.db.list_applied_migrations", side_effect=never_finishes):
        with pytest.raises(TimeoutError):
            await main._read_migration_ledger_with_retry()


@pytest.mark.asyncio
async def test_startup_wraps_ledger_read_failures_with_operator_guidance():
    from fastapi import FastAPI

    from main import lifespan

    operator_log = MagicMock()
    with patch(
        "main._read_migration_ledger_with_retry",
        new_callable=AsyncMock,
        side_effect=PermissionError("permission denied"),
    ), patch("main._log_operator_issue", operator_log):
        with pytest.raises(RuntimeError, match="SELECT permission"):
            async with lifespan(FastAPI()):
                pass

    assert "public.schema_migrations" in operator_log.call_args.args[1]


@pytest.mark.asyncio
async def test_malformed_ledger_stops_startup_without_retry():
    from fastapi import FastAPI

    import main

    error = MigrationLedgerSchemaError("ledger schema is malformed")
    ledger_read = AsyncMock(side_effect=error)
    retry_sleep = AsyncMock()
    operator_log = MagicMock()

    with (
        patch("main.db.list_applied_migrations", ledger_read),
        patch("main.asyncio.sleep", retry_sleep),
        patch("main._log_operator_issue", operator_log),
    ):
        with pytest.raises(MigrationLedgerSchemaError, match="schema is malformed"):
            async with main.lifespan(FastAPI()):
                pass

    ledger_read.assert_awaited_once()
    retry_sleep.assert_not_awaited()
    operator_log.assert_called_once_with(40, "ledger schema is malformed")


@pytest.mark.asyncio
async def test_sqlalchemy_service_reports_missing_ledger():
    from db.sqlalchemy_service import SQLAlchemyService

    session = AsyncMock()
    session.__aenter__.return_value = session
    missing_result = _mapping_result(None)
    session.execute.return_value = missing_result

    service = object.__new__(SQLAlchemyService)
    service.async_session = MagicMock(return_value=session)

    assert await service.list_applied_migrations() is None
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_sqlalchemy_service_returns_sorted_ledger_rows():
    from db.sqlalchemy_service import SQLAlchemyService

    session = AsyncMock()
    session.__aenter__.return_value = session
    schema_result = _mapping_result(_valid_ledger_schema())
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = ["001_init.sql", "008_schema.sql"]
    session.execute.side_effect = (schema_result, rows_result)

    service = object.__new__(SQLAlchemyService)
    service.async_session = MagicMock(return_value=session)

    assert await service.list_applied_migrations() == [
        "001_init.sql",
        "008_schema.sql",
    ]
    assert "ORDER BY filename" in str(session.execute.await_args_list[1].args[0])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("invalid_field", "expected_component"),
    (
        ("is_table", "ordinary table"),
        (
            "has_only_expected_columns",
            "exactly the filename and applied_at columns",
        ),
        ("filename_is_text_not_null", "filename TEXT NOT NULL"),
        ("filename_is_primary_key", "non-deferrable PRIMARY KEY (filename)"),
        (
            "applied_at_is_timestamptz_not_null",
            "applied_at TIMESTAMPTZ NOT NULL",
        ),
        ("applied_at_default_is_now", "applied_at DEFAULT now()"),
    ),
)
async def test_sqlalchemy_service_rejects_malformed_ledger(
    invalid_field, expected_component
):
    from db.sqlalchemy_service import SQLAlchemyService

    schema = _valid_ledger_schema()
    schema[invalid_field] = False
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.return_value = _mapping_result(schema)

    service = object.__new__(SQLAlchemyService)
    service.async_session = MagicMock(return_value=session)

    with pytest.raises(
        MigrationLedgerSchemaError, match=re.escape(expected_component)
    ) as exc_info:
        await service.list_applied_migrations()

    assert "repair it to the expected contract" in str(exc_info.value)
    assert session.execute.await_count == 1


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


def test_live_ledger_matches_filesystem_when_installed(postgres_connection):
    with postgres_connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.schema_migrations')")
        if cursor.fetchone()[0] is None:
            pytest.fail(
                "PostgreSQL is reachable but schema_migrations is not installed; "
                "apply backend/db/init/*.sql before running integration tests"
            )

        cursor.execute(
            "SELECT filename, applied_at "
            "FROM public.schema_migrations ORDER BY filename"
        )
        rows = cursor.fetchall()

    assert tuple(row[0] for row in rows) == migration_filenames()
    assert all(row[1] is not None for row in rows)


@pytest.mark.asyncio
async def test_live_sqlalchemy_service_validates_installed_ledger(postgres_connection):
    from db.sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()
    try:
        assert tuple(await service.list_applied_migrations()) == migration_filenames()
    finally:
        await service.engine.dispose()


def test_backfill_migration_is_idempotent_and_repairs_missing_baseline_row(
    postgres_connection, ledger_sql
):
    schema_name = f"migration_ledger_test_{uuid4().hex}"
    isolated_sql = ledger_sql.replace(
        "public.schema_migrations", f'"{schema_name}".schema_migrations'
    )
    statements = [
        statement.strip()
        for statement in isolated_sql.split(";")
        if statement.strip()
    ]

    postgres_connection.rollback()
    postgres_connection.autocommit = True
    try:
        with postgres_connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema_name}"')
            for _ in range(2):
                for statement in statements:
                    cursor.execute(statement)
            cursor.execute(
                f'DELETE FROM "{schema_name}".schema_migrations '
                "WHERE filename = '007_sessions.sql'"
            )
            for statement in statements:
                cursor.execute(statement)
            cursor.execute(
                f'SELECT filename, applied_at FROM "{schema_name}".schema_migrations '
                "ORDER BY filename"
            )
            rows = cursor.fetchall()
    finally:
        with postgres_connection.cursor() as cursor:
            cursor.execute("ROLLBACK")
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        postgres_connection.autocommit = False

    assert tuple(row[0] for row in rows) == BASELINE_MIGRATION_FILENAMES
    assert all(row[1] is not None for row in rows)

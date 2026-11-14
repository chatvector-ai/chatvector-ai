"""Refuse verification when the shared DB ledger is ahead of this checkout."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

from .models import PipelineError

ReadAppliedFn = Callable[[], set[str] | None]


def expected_migration_filenames(checkout: Path) -> set[str]:
    init_dir = checkout / "backend" / "db" / "init"
    if not init_dir.is_dir():
        return set()
    return {path.name for path in sorted(init_dir.glob("*.sql"))}


def default_read_applied_filenames() -> set[str] | None:
    """Read schema_migrations when DATABASE_URL or PIPELINE_DB_CONTAINER is configured."""

    url = os.environ.get("PIPELINE_VERIFY_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if url:
        return _read_applied_from_url(url)
    container = os.environ.get("PIPELINE_DB_CONTAINER")
    if container:
        return _read_applied_from_docker(container)
    if os.environ.get("PIPELINE_ENFORCE_MIGRATION_LEDGER") == "1":
        raise PipelineError(
            "migration ledger check required but no DATABASE_URL or PIPELINE_DB_CONTAINER is set",
            "verify",
        )
    return None


def assert_migration_ledger_compatible(
    checkout: Path,
    *,
    reader: ReadAppliedFn | None = None,
) -> None:
    """Refuse verify when the DB has migrations this checkout does not ship."""

    expected = expected_migration_filenames(checkout)
    if not expected:
        return
    applied = (reader or default_read_applied_filenames)()
    if applied is None:
        return
    extra = sorted(applied - expected)
    if extra:
        raise PipelineError(
            "database schema_migrations contains filenames not in this checkout's "
            f"backend/db/init: {', '.join(extra)}",
            "verify",
        )


def _read_applied_from_url(url: str) -> set[str] | None:
    sync_url = url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )
    parsed = urlparse(sync_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        return None
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = unquote(parsed.username or "postgres")
    password = unquote(parsed.password or "")
    database = (parsed.path or "/postgres").lstrip("/") or "postgres"
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    completed = subprocess.run(
        [
            "psql",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            database,
            "-At",
            "-c",
            "SELECT filename FROM public.schema_migrations ORDER BY filename",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        if os.environ.get("PIPELINE_ENFORCE_MIGRATION_LEDGER") == "1":
            detail = (completed.stderr or completed.stdout or "").strip()
            raise PipelineError(f"could not read schema_migrations: {detail}", "verify")
        return None
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def _read_applied_from_docker(container: str) -> set[str] | None:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-At",
            "-c",
            "SELECT filename FROM public.schema_migrations ORDER BY filename",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        if os.environ.get("PIPELINE_ENFORCE_MIGRATION_LEDGER") == "1":
            detail = (completed.stderr or completed.stdout or "").strip()
            raise PipelineError(f"could not read schema_migrations via docker: {detail}", "verify")
        return None
    return {line.strip() for line in completed.stdout.splitlines() if line.strip()}


def checkout_is_isolated_from_primary(cwd: Path, primary: Path) -> bool:
    return cwd.resolve() != primary.resolve()

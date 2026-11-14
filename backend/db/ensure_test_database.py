"""Create the isolated pytest database and apply init SQL when needed."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg

logger = logging.getLogger(__name__)

DEFAULT_TEST_DATABASE = "chatvector_test"
_INIT_DIR = Path(__file__).resolve().parent / "init"


def default_test_database_name() -> str:
    return os.getenv("CHATVECTOR_TEST_DATABASE", DEFAULT_TEST_DATABASE).strip()


def to_sync_postgres_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def _connection_params(sync_url: str, database: str | None = None) -> dict[str, str]:
    parsed = urlparse(sync_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ValueError(f"Unsupported database URL scheme: {parsed.scheme!r}")
    db_name = (
        database
        if database is not None
        else (parsed.path or "/postgres").lstrip("/") or "postgres"
    )
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or "postgres"),
        "password": unquote(parsed.password or ""),
        "dbname": db_name,
    }


def admin_database_url(database_url: str | None = None) -> str:
    explicit = os.getenv("DATABASE_ADMIN_URL", "").strip()
    if explicit:
        return to_sync_postgres_url(explicit)
    source = (database_url or os.getenv("DATABASE_URL", "")).strip()
    if not source:
        raise ValueError(
            "Set DATABASE_ADMIN_URL or DATABASE_URL so the test database can be created."
        )
    sync = to_sync_postgres_url(source)
    parsed = urlparse(sync)
    admin_path = "/postgres"
    return parsed._replace(path=admin_path).geturl()


def init_sql_files(init_dir: Path | None = None) -> list[Path]:
    root = init_dir or _INIT_DIR
    return sorted(root.glob("*.sql"), key=lambda path: path.name)


def database_exists(conn_params: dict[str, str], database_name: str) -> bool:
    with psycopg.connect(**conn_params) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
        return row is not None


def create_database(conn_params: dict[str, str], database_name: str) -> bool:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", database_name):
        raise ValueError(f"Invalid database name: {database_name!r}")
    if database_exists(conn_params, database_name):
        return False
    with psycopg.connect(**conn_params, autocommit=True) as conn:
        conn.execute(
            psycopg.sql.SQL("CREATE DATABASE {}").format(
                psycopg.sql.Identifier(database_name)
            )
        )
        return True


def needs_schema_bootstrap(sync_url: str) -> bool:
    """Return True when the target database has not recorded any migrations."""
    params = _connection_params(sync_url)
    with psycopg.connect(**params) as conn:
        regclass = conn.execute(
            "SELECT to_regclass('public.schema_migrations')"
        ).fetchone()[0]
        if regclass is None:
            return True
        count = conn.execute(
            "SELECT COUNT(*) FROM public.schema_migrations"
        ).fetchone()[0]
        return count == 0


def apply_init_sql(
    sync_url: str,
    *,
    init_dir: Path | None = None,
    psql_bin: str | None = None,
) -> None:
    psql = psql_bin or shutil.which("psql")
    if not psql:
        raise RuntimeError("psql not found on PATH; install postgresql-client")

    params = _connection_params(sync_url)
    env = os.environ.copy()
    if params["password"]:
        env["PGPASSWORD"] = params["password"]

    for sql_file in init_sql_files(init_dir):
        completed = subprocess.run(
            [
                psql,
                "-h",
                params["host"],
                "-p",
                params["port"],
                "-U",
                params["user"],
                "-d",
                params["dbname"],
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                str(sql_file),
            ],
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Failed to apply {sql_file.name} to {params['dbname']}: "
                f"{completed.stderr or completed.stdout}"
            )


def target_database_url(
    admin_url: str,
    database_name: str | None = None,
) -> str:
    name = database_name or default_test_database_name()
    parsed = urlparse(admin_url)
    return parsed._replace(path=f"/{name}").geturl()


def ensure_test_database(
    *,
    admin_url: str | None = None,
    database_name: str | None = None,
    init_dir: Path | None = None,
    apply_schema: bool = True,
) -> str:
    """Ensure ``CHATVECTOR_TEST_DATABASE`` exists and return its sync postgres URL."""
    admin = to_sync_postgres_url(
        admin_url or admin_database_url(os.getenv("DATABASE_URL", "").strip())
    )
    name = database_name or default_test_database_name()
    admin_params = _connection_params(admin, database="postgres")

    created = create_database(admin_params, name)
    if created:
        logger.info("Created database %s", name)
    else:
        logger.info("Database %s already exists", name)

    target_url = target_database_url(admin, name)
    if apply_schema and (created or needs_schema_bootstrap(target_url)):
        apply_init_sql(target_url, init_dir=init_dir)
        logger.info("Applied init SQL to %s", name)

    return target_url


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        url = ensure_test_database()
    except Exception as exc:
        logger.error("%s", exc)
        return 1
    print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""
Tests for migration 002: dimensionless vector column.

Strategy: parse the SQL file and assert structural properties.
No live database required — these are static content tests.

What we verify:
- File exists at the expected path
- Targets correct table (document_chunks) and column (embedding)
- Alters to dimensionless vector (no fixed dimension in ALTER statement)
- Guard uses pg_attribute.atttypmod — not just column existence
- atttypmod <> -1 check present — skips ALTER on fresh/dimensionless installs
- Schema filter 'public' present — avoids matching other schemas
- USING clause present for safe pgvector cast
- Re-ingest warning documented for operators
"""
import re
from pathlib import Path

import pytest

SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "db" / "init" / "002_dimensionless_vector.sql"
)


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """Read migration file once per test session."""
    assert SQL_PATH.exists(), f"Migration file missing: {SQL_PATH}"
    return SQL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sql_code(migration_sql) -> str:
    """SQL with comment lines stripped — used for structural assertions."""
    return "\n".join(
        line for line in migration_sql.splitlines()
        if not line.strip().startswith("--")
    )


def test_file_exists():
    """Migration file must exist at backend/db/init/002_dimensionless_vector.sql."""
    assert SQL_PATH.exists()


def test_targets_correct_table(sql_code):
    """Must reference document_chunks in executable SQL, not just comments."""
    assert "document_chunks" in sql_code


def test_targets_embedding_column(sql_code):
    """Must reference the embedding column in executable SQL."""
    assert "embedding" in sql_code


def test_alters_to_dimensionless_vector(sql_code):
    """ALTER statement must target plain vector with no dimension argument."""
    assert re.search(r"TYPE\s+vector\b", sql_code, re.IGNORECASE)


def test_no_fixed_dimension_in_alter(sql_code):
    """ALTER statement must NOT hard-code vector(N) — dimensionless only."""
    assert not re.search(r"vector\s*\(\s*\d+\s*\)", sql_code, re.IGNORECASE)


def test_guard_uses_pg_attribute(sql_code):
    """Guard must use pg_attribute, not information_schema — catches fixed-dimension columns."""
    assert "pg_attribute" in sql_code
    # information_schema only checks existence, not dimension — must not be used as guard
    assert "information_schema" not in sql_code


def test_guard_checks_atttypmod(sql_code):
    """Guard must check atttypmod <> -1 to skip ALTER on already-dimensionless columns."""
    assert "atttypmod" in sql_code
    # Verify the inequality check is present (not just the column name)
    assert re.search(r"atttypmod\s*<>\s*-1", sql_code, re.IGNORECASE)


def test_guard_has_schema_filter(sql_code):
    """Guard must filter to public schema to avoid matching other schemas."""
    assert re.search(r"nspname\s*=\s*'public'", sql_code, re.IGNORECASE)


def test_has_if_exists_block(sql_code):
    """Must use IF EXISTS block so migration is safe to re-run."""
    assert "IF EXISTS" in sql_code.upper()


def test_has_using_clause(sql_code):
    """Must include USING embedding::vector for safe pgvector type cast."""
    assert re.search(r"USING\s+embedding::vector", sql_code, re.IGNORECASE)


def test_has_warning_comment(migration_sql):
    """Migration must document the re-ingest requirement for operators."""
    assert "re-ingest" in migration_sql.lower()

"""
Tests for migration 002: dimensionless vector column.

Strategy: parse the SQL file and assert structural properties.
No live database required — these are static content tests.

What we verify:
- File exists at the expected path
- Targets correct table (document_chunks) and column (embedding)
- Alters to dimensionless vector (no fixed dimension like vector(3072))
- Has an idempotent guard via information_schema.columns
- Includes USING clause for safe pgvector cast
- Documents the re-ingest warning for operators
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


def test_file_exists():
    """Migration file must exist at backend/db/init/002_dimensionless_vector.sql."""
    assert SQL_PATH.exists()


def test_targets_correct_table(migration_sql):
    """Must reference the document_chunks table."""
    assert "document_chunks" in migration_sql


def test_targets_embedding_column(migration_sql):
    """Must reference the embedding column."""
    assert "embedding" in migration_sql


def test_alters_to_dimensionless_vector(migration_sql):
    """Must alter column to plain vector with no dimension argument."""
    # Matches: TYPE vector followed by whitespace or end-of-token (not a parenthesis)
    assert re.search(r"TYPE\s+vector\b", migration_sql, re.IGNORECASE)


def test_no_fixed_dimension(migration_sql):
    """Must NOT hard-code vector(N) in SQL statements — comments are excluded."""
    # Strip comment lines so vector(3072) in comments doesn't trigger false failure
    sql_code = "\n".join(
        line for line in migration_sql.splitlines()
        if not line.strip().startswith("--")
    )
    assert not re.search(r"vector\s*\(\s*\d+\s*\)", sql_code, re.IGNORECASE)


def test_has_idempotent_guard(migration_sql):
    """Must check column existence before altering — safe to re-run."""
    assert "information_schema.columns" in migration_sql
    assert "IF EXISTS" in migration_sql.upper()


def test_has_using_clause(migration_sql):
    """Must include USING embedding::vector for safe pgvector type cast."""
    assert re.search(r"USING\s+embedding::vector", migration_sql, re.IGNORECASE)


def test_has_warning_comment(migration_sql):
    """Migration must document the re-ingest requirement for operators."""
    assert "re-ingest" in migration_sql.lower()

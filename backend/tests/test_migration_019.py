"""Tests for migration 019: document_chunks.page_end (PDF span citations)."""

from __future__ import annotations

import re
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "db" / "init" / "019_document_chunks_page_end.sql"
)
MIGRATION_FILENAME = "019_document_chunks_page_end.sql"


def _executable_sql() -> str:
    return "\n".join(
        line
        for line in MIGRATION_PATH.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ).strip()


def test_migration_file_exists():
    assert MIGRATION_PATH.is_file()


def test_migration_adds_nullable_page_end_only():
    sql = _executable_sql()
    assert re.match(r"BEGIN\s*;", sql, re.IGNORECASE)
    assert "document_chunks" in sql
    assert "page_end" in sql
    assert "ADD COLUMN IF NOT EXISTS page_end" in sql
    assert "DEFAULT" not in sql
    assert "CREATE INDEX" not in sql
    assert "chat_messages" not in sql
    assert MIGRATION_FILENAME in sql
    assert re.search(
        r"ON\s+CONFLICT\s*\(\s*filename\s*\)\s+DO\s+NOTHING\s*;"
        r"\s*COMMIT\s*;\s*$",
        sql,
        re.IGNORECASE,
    )


def test_orm_document_chunk_declares_page_end():
    from core.models import DocumentChunk

    assert "page_end" in DocumentChunk.__table__.columns
    column = DocumentChunk.__table__.columns["page_end"]
    assert column.nullable is True

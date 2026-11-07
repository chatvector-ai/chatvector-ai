"""
Tests for context_service.build_context_from_chunks.

Covers:
- Empty input
- Normal concatenation + source labelling
- Truncation at MAX_CONTEXT_CHARS (whole-chunk boundary, no mid-string slicing)
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.session import SessionContext
from services.context_service import build_context_from_chunks


def _chunk(
    text: str,
    file_name: str = "doc.pdf",
    page_number: int | None = None,
    *,
    document_id: str | None = None,
    chunk_index: int | None = None,
):
    return SimpleNamespace(
        chunk_text=text,
        file_name=file_name,
        page_number=page_number,
        document_id=document_id,
        chunk_index=chunk_index,
    )


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

def test_empty_chunks_returns_empty_string():
    packed = build_context_from_chunks([])
    assert packed.text == ""
    assert packed.included_chunks == ()


# ---------------------------------------------------------------------------
# Normal formatting
# ---------------------------------------------------------------------------

def test_single_chunk_no_page():
    chunk = _chunk("Hello world", file_name="a.pdf")
    result = build_context_from_chunks([chunk]).text
    assert result == "[Source: a.pdf]\nHello world"


def test_single_chunk_with_page():
    chunk = _chunk("Hello world", file_name="a.pdf", page_number=3)
    result = build_context_from_chunks([chunk]).text
    assert result == "[Source: a.pdf, page 3]\nHello world"


def test_multiple_chunks_joined_by_double_newline():
    chunks = [
        _chunk("First", file_name="a.pdf", page_number=1),
        _chunk("Second", file_name="b.pdf", page_number=2),
    ]
    result = build_context_from_chunks(chunks).text
    parts = result.split("\n\n")
    assert len(parts) == 2
    assert parts[0] == "[Source: a.pdf, page 1]\nFirst"
    assert parts[1] == "[Source: b.pdf, page 2]\nSecond"


def test_unknown_file_name_fallback():
    chunk = _chunk("text", file_name=None)
    result = build_context_from_chunks([chunk]).text
    assert "[Source: unknown]" in result


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def test_truncation_drops_whole_chunks():
    """All chunks that would exceed the cap are dropped entirely — no partial text."""
    small = "x" * 100
    chunks = [_chunk(small, file_name=f"f{i}.pdf") for i in range(10)]

    # Set a cap that fits exactly 3 chunks (generous estimate; test asserts ≥ 1 dropped)
    cap = 400
    with patch("services.context_service.MAX_CONTEXT_CHARS", cap):
        packed = build_context_from_chunks(chunks)
    result = packed.text

    # Result must be strictly shorter than or equal to cap
    assert len(result) <= cap

    # Every chunk that appears is complete — no mid-string truncation
    for part in result.split("\n\n"):
        assert part.endswith(small)


def test_truncation_logs_warning(caplog):
    chunks = [_chunk("a" * 200, file_name=f"f{i}.pdf") for i in range(5)]
    cap = 300
    import logging
    with patch("services.context_service.MAX_CONTEXT_CHARS", cap):
        with caplog.at_level(logging.WARNING, logger="services.context_service"):
            build_context_from_chunks(chunks)
    assert any("truncated" in record.message.lower() for record in caplog.records)


def test_no_truncation_when_within_limit():
    chunks = [_chunk("short", file_name=f"f{i}.pdf") for i in range(3)]
    cap = 10_000
    with patch("services.context_service.MAX_CONTEXT_CHARS", cap):
        packed = build_context_from_chunks(chunks)
    assert packed.text.count("[Source:") == 3
    assert packed.included_chunks == tuple(chunks)


def test_oversized_single_chunk_is_still_included():
    """A single chunk larger than the cap passes through (no mid-string slicing)."""
    big_text = "y" * 50_000
    chunk = _chunk(big_text, file_name="big.pdf")
    cap = 100
    with patch("services.context_service.MAX_CONTEXT_CHARS", cap):
        packed = build_context_from_chunks([chunk])
    assert big_text in packed.text
    assert packed.included_chunks == (chunk,)

# ---------------------------------------------------------------------------
# Session Context
# ---------------------------------------------------------------------------

def test_session_context_included():
    chunks = [_chunk("short", file_name="f1.pdf")]
    session_ctx = SessionContext(
        recent_queries=["hello?", "what is this?"],
        active_documents=["f1.pdf"]
    )
    result = build_context_from_chunks(chunks, session_context=session_ctx).text
    
    assert "[Session History]" in result
    assert "Recent queries: hello?, what is this?" in result
    assert "Active documents: f1.pdf" in result
    assert "[Retrieved Context]" in result
    assert "short" in result

def test_session_context_truncates_chunks():
    """If session context takes up space, chunks should be truncated earlier."""
    session_ctx = SessionContext(recent_queries=["x" * 200])
    chunks = [_chunk("c" * 200, file_name=f"f{i}.pdf") for i in range(5)]
    
    cap = 500
    with patch("services.context_service.MAX_CONTEXT_CHARS", cap):
        result = build_context_from_chunks(chunks, session_context=session_ctx).text
        
    assert "[Session History]" in result
    assert len(result) <= cap
    # The session context is ~200 chars. We only have ~300 chars left for chunks.
    # Each chunk is ~200 chars + formatting, so only 1 chunk should fit.
    assert result.count("[Source:") == 1


def test_inclusion_list_does_not_change_the_context_string():
    """The string stays the labeled join. Inclusion is the chunk objects, not a scan of that string."""
    chunks = [
        _chunk("First", file_name="a.pdf", page_number=1, document_id="doc-a", chunk_index=0),
        _chunk("Second", file_name="b.pdf", page_number=2, document_id="doc-b", chunk_index=1),
    ]
    packed = build_context_from_chunks(chunks)
    assert packed.text == (
        "[Source: a.pdf, page 1]\nFirst\n\n[Source: b.pdf, page 2]\nSecond"
    )
    assert packed.included_chunks == tuple(chunks)
    assert [(chunk.document_id, chunk.chunk_index, chunk.page_number) for chunk in packed.included_chunks] == [
        ("doc-a", 0, 1),
        ("doc-b", 1, 2),
    ]


def test_cap_keeps_two_of_three_chunks_on_the_inclusion_list():
    chunks = [
        _chunk("x" * 10, file_name="a.pdf", document_id="doc-a", chunk_index=index)
        for index in range(3)
    ]
    first_two = build_context_from_chunks(chunks[:2])
    packed = build_context_from_chunks(chunks, max_chars=len(first_two.text))
    assert packed.text == first_two.text
    assert [chunk.chunk_index for chunk in packed.included_chunks] == [0, 1]
    assert chunks[2] not in packed.included_chunks


def test_session_history_that_fills_the_cap_omits_selected_chunks():
    session_ctx = SessionContext(recent_queries=["q" * 40], chat_history=[{"role": "user", "content": "earlier"}])
    chunks = [
        _chunk("evidence", file_name="a.pdf", document_id="doc-a", chunk_index=index)
        for index in range(3)
    ]
    session_only = build_context_from_chunks([], session_context=session_ctx)
    packed = build_context_from_chunks(
        chunks,
        session_context=session_ctx,
        max_chars=len(session_only.text),
    )
    assert packed.included_chunks == ()
    assert packed.text == session_only.text

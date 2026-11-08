"""DOCX-specific text cleaning preserves table delimiters."""

from services.text_cleaning_service import clean_docx_text, clean_text


def test_clean_docx_text_preserves_table_delimiters():
    raw = "Intro paragraph.\n\nfee-only-7741\tneighbor\nrow-two-a\trow-two-b"
    cleaned = clean_docx_text(raw)
    assert cleaned == (
        "Intro paragraph.\n\nfee-only-7741\tneighbor\nrow-two-a\trow-two-b"
    )
    assert clean_text(raw) == (
        "Intro paragraph.\n\nfee-only-7741 neighbor row-two-a row-two-b"
    )


def test_clean_docx_text_collapses_whitespace_inside_cells():
    raw = "Alpha   cell\tBeta   cell"
    assert clean_docx_text(raw) == "Alpha cell\tBeta cell"

"""Document extractor interface, registry/factory, and PDF/TXT regression tests."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import UploadFile

from services import extraction_service
from services.docx_extraction import (
    DOCX_CONTENT_TYPE,
    DocxExtractionError,
    extract_docx_text,
    is_docx_content_type,
    is_docx_filename,
)
from services.extraction_service import (
    DocxExtractor,
    DocumentExtractionError,
    DocumentExtractor,
    ExtractedDocument,
    HtmlExtractor,
    MarkdownExtractor,
    PageBoundary,
    PdfExtractor,
    PlainTextExtractor,
    UnsupportedDocumentTypeError,
    build_document_extractor,
    extract_text_from_file,
    extract_text_with_metadata,
    is_html_content_type,
    is_html_filename,
    is_markdown_content_type,
    is_markdown_filename,
    prepare_extracted_document_for_chunking,
    register_document_extractor,
)
from tests.docx_fixtures import (
    build_encrypted_docx_stub,
    build_minimal_docx,
    build_zip_bomb_like_docx,
)
from services.ingestion_pipeline import (
    IngestionPipeline,
    UploadPipelineError,
    _build_chunk_records,
)


def _make_pdf(page_texts: list[str]) -> bytes:
    """Build a minimal text PDF with one Helvetica text line per page."""
    objects: list[bytes] = []
    n_pages = len(page_texts)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, text in enumerate(page_texts):
        content_id = 4 + 2 * i
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_id} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            ).encode()
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj_id, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{obj_id} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _upload(content_type: str, filename: str = "doc") -> UploadFile:
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = filename
    mock_file.content_type = content_type
    return mock_file


class _DummyExtractor(DocumentExtractor):
    def extract(self, contents: bytes, *, filename: str = "") -> ExtractedDocument:
        return ExtractedDocument(
            text=contents.decode("ascii").upper(),
            warnings=["dummy warning"],
        )


class _FailingExtractor(DocumentExtractor):
    def extract(self, contents: bytes, *, filename: str = "") -> ExtractedDocument:
        raise DocumentExtractionError("stub extraction failure")


@pytest.fixture
def registry(monkeypatch):
    """Isolated copy of the extractor registry so tests never leak registrations."""
    isolated = dict(extraction_service._EXTRACTOR_REGISTRY)
    monkeypatch.setattr(extraction_service, "_EXTRACTOR_REGISTRY", isolated)
    return isolated


# ---------------------------------------------------------------------------
# Factory / registry
# ---------------------------------------------------------------------------


def test_factory_selects_extractor_for_allowlisted_types():
    assert isinstance(build_document_extractor("application/pdf"), PdfExtractor)
    assert isinstance(build_document_extractor("text/plain"), PlainTextExtractor)
    assert isinstance(build_document_extractor("text/html"), HtmlExtractor)
    assert isinstance(build_document_extractor("text/markdown"), MarkdownExtractor)
    assert isinstance(build_document_extractor("text/x-markdown"), MarkdownExtractor)
    assert isinstance(build_document_extractor(DOCX_CONTENT_TYPE), DocxExtractor)


def test_factory_normalizes_mime_type():
    assert isinstance(build_document_extractor("Application/PDF"), PdfExtractor)
    assert isinstance(
        build_document_extractor("text/plain; charset=utf-8", filename="a.txt"),
        PlainTextExtractor,
    )


def test_factory_returns_fresh_instance_per_call():
    assert build_document_extractor("text/plain") is not build_document_extractor("text/plain")


@pytest.mark.parametrize("content_type", [None, "", "image/png", "application/msword"])
def test_factory_rejects_unsupported_types(content_type):
    with pytest.raises(UnsupportedDocumentTypeError) as excinfo:
        build_document_extractor(content_type, filename="x")

    assert isinstance(excinfo.value, ValueError)
    assert f"Unsupported file type: {content_type}" == str(excinfo.value)


def test_default_extractors_hold_no_instance_state():
    assert vars(PdfExtractor()) == {}
    assert vars(PlainTextExtractor()) == {}


# ---------------------------------------------------------------------------
# DocxExtractor
# ---------------------------------------------------------------------------


def test_docx_extractor_extracts_paragraphs_headings_and_tables_in_order():
    docx_bytes = build_minimal_docx(
        paragraphs=["DOCX Fixture Heading", "Unique docx paragraph phrase."],
        table_rows=[["Alpha cell", "Beta cell"], ["Gamma cell", "Delta cell"]],
    )
    doc = DocxExtractor().extract(docx_bytes, filename="fixture.docx")

    assert "DOCX Fixture Heading" in doc.text
    assert "Unique docx paragraph phrase." in doc.text
    assert "Alpha cell\tBeta cell" in doc.text
    assert "Gamma cell\tDelta cell" in doc.text
    assert doc.page_boundaries == []


def test_prepare_extracted_docx_preserves_table_cell_and_row_boundaries():
    docx_bytes = build_minimal_docx(
        paragraphs=["Prose paragraph unchanged wording."],
        table_rows=[
            ["fee-only-7741", "neighbor-cell-992"],
            ["row-two-a", "row-two-b"],
        ],
    )
    doc = DocxExtractor().extract(docx_bytes, filename="fixture.docx")
    stored, boundaries = prepare_extracted_document_for_chunking(
        doc.text,
        doc.page_boundaries,
        content_type=DOCX_CONTENT_TYPE,
    )

    assert boundaries == []
    assert "Prose paragraph unchanged wording." in stored
    assert "fee-only-7741\tneighbor-cell-992" in stored
    assert "row-two-a\trow-two-b" in stored
    assert "fee-only-7741 neighbor-cell-992" not in stored
    assert "fee-only-7741\tneighbor-cell-992\nrow-two-a\trow-two-b" in stored


def test_prepare_extracted_docx_prose_only_matches_clean_text():
    docx_bytes = build_minimal_docx(paragraphs=["Unique prose-only docx phrase."])
    doc = DocxExtractor().extract(docx_bytes, filename="prose.docx")
    stored, _ = prepare_extracted_document_for_chunking(
        doc.text,
        doc.page_boundaries,
        content_type=DOCX_CONTENT_TYPE,
    )
    plain, _ = prepare_extracted_document_for_chunking(doc.text, doc.page_boundaries)
    assert stored == plain == "Unique prose-only docx phrase."


def test_docx_content_type_and_filename_helpers():
    assert is_docx_content_type(DOCX_CONTENT_TYPE)
    assert is_docx_content_type(f"{DOCX_CONTENT_TYPE}; charset=binary")
    assert not is_docx_content_type("text/plain")
    assert is_docx_filename("report.docx")
    assert is_docx_filename("Report.DOCX")
    assert not is_docx_filename("report.pdf")


def test_docx_extractor_rejects_corrupt_and_encrypted_packages():
    with pytest.raises(DocumentExtractionError, match="Failed to parse DOCX content."):
        DocxExtractor().extract(b"not-a-zip", filename="bad.docx")

    with pytest.raises(DocumentExtractionError, match="Encrypted DOCX"):
        DocxExtractor().extract(build_encrypted_docx_stub(), filename="locked.docx")


def test_docx_zip_bomb_like_fixture_fails_safely(monkeypatch):
    monkeypatch.setattr("services.docx_extraction.config.DOCX_MAX_COMPRESSION_RATIO", 5)
    monkeypatch.setattr(
        "services.docx_extraction.config.DOCX_MAX_UNCOMPRESSED_BYTES", 50_000
    )
    with pytest.raises(DocxExtractionError):
        extract_docx_text(build_zip_bomb_like_docx(), filename="bomb.docx")


@pytest.mark.asyncio
async def test_extract_text_with_metadata_docx():
    docx_bytes = build_minimal_docx(paragraphs=["Async docx fixture phrase"])
    text, boundaries = await extract_text_with_metadata(
        _upload(DOCX_CONTENT_TYPE, "notes.docx"),
        docx_bytes,
    )
    assert "Async docx fixture phrase" in text
    assert boundaries == []


# ---------------------------------------------------------------------------
# PlainTextExtractor
# ---------------------------------------------------------------------------


def test_plain_text_extractor_decodes_utf8_with_empty_boundaries():
    doc = PlainTextExtractor().extract("héllo wörld".encode("utf-8"))

    assert doc.text == "héllo wörld"
    assert doc.page_boundaries == []
    assert doc.warnings == []


def test_plain_text_extractor_falls_back_to_cp1254():
    raw = "ışık".encode("cp1254")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")

    assert PlainTextExtractor().extract(raw).text == "ışık"


def test_plain_text_extractor_raises_structured_error_on_undecodable_bytes():
    # 0xFF is invalid utf-8 and 0x81 is undefined in cp1254.
    with pytest.raises(DocumentExtractionError):
        PlainTextExtractor().extract(b"\xff\x81")


# ---------------------------------------------------------------------------
# MarkdownExtractor
# ---------------------------------------------------------------------------


_MARKDOWN_FIXTURE = b"""# Product Guide

A short overview paragraph for ingestion tests.

- First list item phrase
- Second list item phrase

```python
def sample_code_block():
    return "fixture code phrase"
```

See [Example Link](https://example.com/ignored) for details.

<p>Inline HTML paragraph phrase</p>
<script>alert("must not run")</script>
"""


def test_markdown_extractor_preserves_structure_and_normalizes_links():
    doc = MarkdownExtractor().extract(_MARKDOWN_FIXTURE, filename="guide.md")

    assert "# Product Guide" in doc.text
    assert "First list item phrase" in doc.text
    assert 'return "fixture code phrase"' in doc.text
    assert "Example Link" in doc.text
    assert "https://example.com/ignored" not in doc.text
    assert "Inline HTML paragraph phrase" in doc.text
    assert "alert" not in doc.text
    assert doc.page_boundaries == []


def test_markdown_embedded_html_table_cells_survive_cleaning():
    payload = b"""# Product Guide

Plain markdown paragraph unchanged.

<table><tr><td>Parachute flares</td><td>88421</td></tr></table>

See [Example Link](https://example.com/ignored) for details.
"""
    doc = MarkdownExtractor().extract(payload, filename="mixed.md")
    cleaned, boundaries = prepare_extracted_document_for_chunking(doc.text, doc.page_boundaries)

    assert "Plain markdown paragraph unchanged." in cleaned
    assert "88421" in cleaned
    assert "flares88421" not in cleaned
    assert "Parachute flares 88421" in cleaned
    assert "Example Link" in cleaned
    assert "https://example.com/ignored" not in cleaned
    assert boundaries == []


def test_markdown_content_type_and_filename_helpers():
    assert is_markdown_content_type("text/markdown")
    assert is_markdown_content_type("Text/Markdown; charset=utf-8")
    assert not is_markdown_content_type("text/plain")
    assert is_markdown_filename("notes.md")
    assert is_markdown_filename("Guide.MARKDOWN")
    assert not is_markdown_filename("notes.txt")


def test_markdown_extractor_raises_on_null_bytes():
    with pytest.raises(DocumentExtractionError, match="Failed to parse Markdown content."):
        MarkdownExtractor().extract(b"# Title\x00broken", filename="bad.md")


@pytest.mark.asyncio
async def test_extract_text_with_metadata_markdown():
    text, boundaries = await extract_text_with_metadata(
        _upload("text/markdown", "guide.md"),
        _MARKDOWN_FIXTURE,
    )
    assert "Product Guide" in text
    assert boundaries == []


# ---------------------------------------------------------------------------
# HtmlExtractor
# ---------------------------------------------------------------------------


_HTML_FIXTURE = b"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Fixture Page</title></head>
<body>
  <h1>HTML Ingest Fixture</h1>
  <p>Unique visible phrase for HTML ingestion tests.</p>
  <style>body { display: none; } secret-style-phrase</style>
  <script>alert("must-not-persist-script")</script>
  <img src="http://example.com/remote-only.png" alt="ignored remote asset">
</body>
</html>
"""


def test_html_extractor_strips_script_and_style():
    doc = HtmlExtractor().extract(_HTML_FIXTURE, filename="page.html")

    assert "HTML Ingest Fixture" in doc.text
    assert "Unique visible phrase for HTML ingestion tests." in doc.text
    assert "secret-style-phrase" not in doc.text
    assert "must-not-persist-script" not in doc.text
    assert doc.page_boundaries == []


_HTML_TABLE_FIXTURE = b"""<!DOCTYPE html>
<html><body>
  <p>Prose sentence without the table-only value.</p>
  <table>
    <tr><td>Parachute flares</td><td>88421</td></tr>
    <tr><td>Handheld flares</td><td>6</td></tr>
  </table>
</body></html>
"""

_HTML_PROSE_CLEANED_BASELINE = (
    "Fixture Page\n\nHTML Ingest Fixture Unique visible phrase for HTML ingestion tests."
)


def test_html_table_cells_and_rows_survive_cleaning():
    doc = HtmlExtractor().extract(_HTML_TABLE_FIXTURE, filename="inventory.html")
    cleaned, boundaries = prepare_extracted_document_for_chunking(doc.text, doc.page_boundaries)

    assert "88421" in cleaned
    assert "flares88421" not in cleaned
    assert "flares6" not in cleaned
    assert "Parachute flares 88421" in cleaned
    assert "Handheld flares 6" in cleaned
    assert "\n\n" in cleaned
    assert "Prose sentence without the table-only value." in cleaned
    assert boundaries == []


def test_html_extractor_header_cells_survive_cleaning():
    fixture = b"<table><tr><th>Parachute flares</th><th>88421</th></tr></table>"
    doc = HtmlExtractor().extract(fixture, filename="headers.html")
    cleaned, _ = prepare_extracted_document_for_chunking(doc.text, doc.page_boundaries)

    assert "88421" in cleaned
    assert "flares88421" not in cleaned
    assert "Parachute flares 88421" in cleaned


def test_html_prose_only_fixture_unchanged_after_cleaning():
    doc = HtmlExtractor().extract(_HTML_FIXTURE, filename="page.html")
    cleaned, boundaries = prepare_extracted_document_for_chunking(doc.text, doc.page_boundaries)

    assert cleaned == _HTML_PROSE_CLEANED_BASELINE
    assert boundaries == []


def test_html_extractor_respects_declared_charset():
    body = "Caf\xe9 phrase".encode("iso-8859-1")
    wrapped = (
        b'<!DOCTYPE html><html><head><meta charset="iso-8859-1"></head><body>'
        + body
        + b"</body></html>"
    )
    doc = HtmlExtractor().extract(wrapped, filename="latin.html")
    assert "Café phrase" in doc.text


def test_html_extractor_malformed_html_best_effort():
    broken = b"<html><body><p>Unclosed paragraph phrase<div>More visible text</style>"
    doc = HtmlExtractor().extract(broken, filename="broken.html")
    assert "Unclosed paragraph phrase" in doc.text
    assert "More visible text" in doc.text


def test_html_extractor_raises_on_null_bytes():
    with pytest.raises(DocumentExtractionError, match="Failed to parse HTML content."):
        HtmlExtractor().extract(b"<html>\x00<body></body></html>", filename="bad.html")


def test_html_extractor_raises_on_undecodable_bytes():
    with pytest.raises(DocumentExtractionError, match="Failed to decode HTML content."):
        HtmlExtractor().extract(b"\xff\x81", filename="binary.html")


def test_html_extractor_performs_no_network_io():
    with patch("urllib.request.urlopen") as mock_urlopen, patch(
        "socket.create_connection"
    ) as mock_connect:
        HtmlExtractor().extract(_HTML_FIXTURE, filename="page.html")

    mock_urlopen.assert_not_called()
    mock_connect.assert_not_called()


def test_html_content_type_and_filename_helpers():
    assert is_html_content_type("text/html")
    assert is_html_content_type("Text/HTML; charset=utf-8")
    assert not is_html_content_type("text/plain")
    assert is_html_filename("page.html")
    assert is_html_filename("legacy.HTM")
    assert not is_html_filename("page.txt")


@pytest.mark.asyncio
async def test_extract_text_with_metadata_html():
    text, boundaries = await extract_text_with_metadata(
        _upload("text/html", "page.html"),
        _HTML_FIXTURE,
    )
    assert "Unique visible phrase for HTML ingestion tests." in text
    assert boundaries == []


# ---------------------------------------------------------------------------
# PdfExtractor
# ---------------------------------------------------------------------------


def test_pdf_extractor_produces_contiguous_page_boundaries():
    doc = PdfExtractor().extract(_make_pdf(["First page", "Second page"]))

    assert doc.text == "First page\nSecond page\n"
    assert doc.page_boundaries == [
        PageBoundary(page_number=1, start_offset=0, end_offset=len("First page\n")),
        PageBoundary(
            page_number=2,
            start_offset=len("First page\n"),
            end_offset=len("First page\nSecond page\n"),
        ),
    ]


def test_pdf_extractor_raises_structured_error_on_corrupt_bytes():
    with pytest.raises(DocumentExtractionError, match="Failed to parse PDF content."):
        PdfExtractor().extract(b"%PDF-1.4 definitely not a pdf")


def test_pdf_provenance_survives_cleaning_into_chunk_page_numbers():
    doc = PdfExtractor().extract(_make_pdf(["Alpha content", "Beta content"]))

    text, boundaries = prepare_extracted_document_for_chunking(doc.text, doc.page_boundaries)

    assert text == "Alpha content Beta content"
    assert boundaries == [
        PageBoundary(page_number=1, start_offset=0, end_offset=13),
        PageBoundary(page_number=2, start_offset=14, end_offset=26),
    ]

    class _Chunk:
        def __init__(self, page_content: str, start_index: int):
            self.page_content = page_content
            self.metadata = {"start_index": start_index}

    records = _build_chunk_records(
        [_Chunk("Alpha content", 0), _Chunk("Beta content", 14)],
        [[0.1], [0.2]],
        boundaries,
    )
    assert [(r.page_number, r.character_offset_start, r.character_offset_end) for r in records] == [
        (1, 0, 13),
        (2, 14, 26),
    ]


# ---------------------------------------------------------------------------
# Public async entry points (behavior preserved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_text_with_metadata_pdf_and_txt_match_extractors():
    pdf_bytes = _make_pdf(["One", "Two"])

    text, boundaries = await extract_text_with_metadata(_upload("application/pdf"), pdf_bytes)
    assert text == "One\nTwo\n"
    assert [b.page_number for b in boundaries] == [1, 2]

    text, boundaries = await extract_text_with_metadata(_upload("text/plain"), b"plain body")
    assert (text, boundaries) == ("plain body", [])


@pytest.mark.asyncio
async def test_extract_text_with_metadata_reads_file_when_contents_omitted():
    upload = _upload("text/plain")
    upload.read = AsyncMock(return_value=b"from upload")

    assert await extract_text_with_metadata(upload) == ("from upload", [])
    assert await extract_text_from_file(upload, b"explicit") == "explicit"


@pytest.mark.asyncio
async def test_extract_text_with_metadata_unsupported_type_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported file type: image/png"):
        await extract_text_with_metadata(_upload("image/png"), b"x")


@pytest.mark.asyncio
async def test_extract_text_with_metadata_is_safe_under_concurrent_calls():
    payloads = [f"document {i}".encode() for i in range(25)]

    results = await asyncio.gather(
        *(extract_text_with_metadata(_upload("text/plain"), p) for p in payloads)
    )

    assert [text for text, _ in results] == [p.decode() for p in payloads]


# ---------------------------------------------------------------------------
# Registry extension without pipeline edits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registered_dummy_extractor_runs_through_factory(registry):
    register_document_extractor("application/x-dummy", _DummyExtractor)

    assert isinstance(build_document_extractor("application/x-dummy"), _DummyExtractor)
    text, boundaries = await extract_text_with_metadata(_upload("application/x-dummy"), b"abc")

    assert (text, boundaries) == ("ABC", [])


@pytest.mark.asyncio
async def test_registered_dummy_extractor_runs_through_unmodified_pipeline(registry):
    register_document_extractor("application/x-dummy", _DummyExtractor)
    pipeline = IngestionPipeline()

    with patch("services.ingestion_pipeline.db.update_document_status", new=AsyncMock()), patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])
    ), patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings",
        new=AsyncMock(return_value=["c1"]),
    ) as mock_store:
        await pipeline.process_document_background(
            doc_id="doc-dummy",
            file_name="doc.dummy",
            content_type="application/x-dummy",
            file_bytes=b"hello dummy",
            tenant_id="dev",
        )

    stored_records = mock_store.await_args.args[1]
    assert [r.chunk_text for r in stored_records] == ["HELLO DUMMY"]


# ---------------------------------------------------------------------------
# Pipeline failure and validation behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extractor_failure_marks_document_failed_without_storing_chunks(registry):
    register_document_extractor("application/x-fail", _FailingExtractor)
    pipeline = IngestionPipeline()

    with patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock()
    ) as mock_embed, patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock()
    ) as mock_store:
        with pytest.raises(DocumentExtractionError, match="stub extraction failure"):
            await pipeline.process_document_background(
                doc_id="doc-fail",
                file_name="doc.fail",
                content_type="application/x-fail",
                file_bytes=b"anything",
                tenant_id="dev",
            )

    mock_store.assert_not_awaited()
    mock_embed.assert_not_awaited()
    mock_cleanup.assert_awaited_once_with("doc-fail", tenant_id="dev")
    final_update = mock_update.await_args_list[-1].kwargs
    assert final_update["status"] == "failed"
    assert final_update["error"]["stage"] == "extracting"
    assert final_update["error"]["code"] == "pipeline_error"


@pytest.mark.asyncio
async def test_corrupt_pdf_marks_document_failed_without_storing_chunks():
    pipeline = IngestionPipeline()

    with patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ), patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock()
    ) as mock_store:
        with pytest.raises(DocumentExtractionError):
            await pipeline.process_document_background(
                doc_id="doc-corrupt",
                file_name="bad.pdf",
                content_type="application/pdf",
                file_bytes=b"%PDF-1.4 corrupt",
                tenant_id="dev",
            )

    mock_store.assert_not_awaited()
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "extracting"


@pytest.mark.asyncio
async def test_disallowed_type_is_rejected_at_validation_before_extraction(registry):
    # Even with an extractor registered, the upload allowlist stays authoritative.
    register_document_extractor("application/x-dummy", _DummyExtractor)
    pipeline = IngestionPipeline()

    with patch(
        "services.ingestion_pipeline.extract_text_with_metadata", new=AsyncMock()
    ) as mock_extract, patch(
        "services.ingestion_pipeline.db.create_document", new=AsyncMock()
    ) as mock_create:
        upload = _upload("application/x-dummy", "doc.dummy")
        upload.read = AsyncMock(return_value=b"x")
        with pytest.raises(UploadPipelineError) as excinfo:
            await pipeline.process_document(upload, tenant_id="dev")

    assert excinfo.value.code == "invalid_file_type"
    assert excinfo.value.stage == "validation"
    mock_extract.assert_not_awaited()
    mock_create.assert_not_awaited()

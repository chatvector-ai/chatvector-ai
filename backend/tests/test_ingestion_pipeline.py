"""Ingestion pipeline tests for validation, status tracking, and failure handling."""

import sys
import types
from unittest.mock import AsyncMock, call, patch

import pytest
from fastapi import UploadFile

try:
    from google import genai as _genai  # noqa: F401
except Exception:
    google_module = sys.modules.get("google", types.ModuleType("google"))

    class _FakeGenAIClient:
        def __init__(self, api_key=None):
            self.models = types.SimpleNamespace(embed_content=lambda **kwargs: None)

    google_module.genai = types.SimpleNamespace(Client=_FakeGenAIClient)
    sys.modules["google"] = google_module

try:
    from pypdf import PdfReader as _PdfReader  # noqa: F401
except Exception:
    pypdf_module = types.ModuleType("pypdf")

    class _FakePdfReader:
        def __init__(self, *args, **kwargs):
            self.pages = []

    pypdf_module.PdfReader = _FakePdfReader
    sys.modules["pypdf"] = pypdf_module

from db.base import ChunkRecord
from tests.docx_fixtures import build_encrypted_docx_stub, build_minimal_docx

from services.ingestion_pipeline import (
    FixedChunkingStrategy,
    IngestionPipeline,
    ParagraphChunkingStrategy,
    RecursiveCharacterTextSplitter,
    SemanticChunkingStrategy,
    UploadPipelineError,
    _build_chunk_records,
    _classify_ingestion_error,
    _resolve_page_number,
    _resolve_page_span,
)
from services.extraction_service import DocumentExtractionError, PageBoundary


class _FakeDoc:
    """Minimal stand-in for a LangChain Document object."""

    def __init__(self, text: str, start_index: int, **metadata):
        self.page_content = text
        self.metadata = {"start_index": start_index, **metadata}


class _FixedSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int, add_start_index: bool = False):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.add_start_index = add_start_index

    def create_documents(self, texts: list[str]) -> list[_FakeDoc]:
        return [_FakeDoc("chunk-a", 0), _FakeDoc("chunk-b", 7)]

    def split_text(self, text: str) -> list[str]:
        return ["chunk-a", "chunk-b"]


class _SingleChunkSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int, add_start_index: bool = False):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.add_start_index = add_start_index

    def create_documents(self, texts: list[str]) -> list[_FakeDoc]:
        return [_FakeDoc("chunk-a", 0)]

    def split_text(self, text: str) -> list[str]:
        return ["chunk-a"]


class _ManyChunkSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int, add_start_index: bool = False):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.add_start_index = add_start_index

    def create_documents(self, texts: list[str]) -> list[_FakeDoc]:
        return [_FakeDoc(f"chunk-{index}", index) for index in range(25)]

    def split_text(self, text: str) -> list[str]:
        return [f"chunk-{index}" for index in range(25)]


class _TrackingSplitter:
    last_init: dict | None = None
    last_create: dict | None = None

    def __init__(self, chunk_size: int, chunk_overlap: int, add_start_index: bool = False):
        type(self).last_init = {
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "add_start_index": add_start_index,
        }

    def create_documents(self, texts: list[str], metadatas: list[dict] | None = None) -> list[_FakeDoc]:
        type(self).last_create = {
            "texts": texts,
            "metadatas": metadatas,
        }
        metadata = (metadatas or [{}])[0]
        return [_FakeDoc(texts[0], 0, **metadata)]


def _doc_snapshots(docs: list) -> list[tuple[str, int | None, str | None]]:
    return [
        (
            doc.page_content,
            doc.metadata.get("start_index"),
            doc.metadata.get("heading"),
        )
        for doc in docs
    ]


@pytest.mark.asyncio
async def test_process_document_success_tracks_status_and_returns_status_endpoint(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"%PDF-fake-pdf-bytes")

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_MB", 10)

    pipeline = IngestionPipeline(splitter_cls=_FixedSplitter)

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc123")) as mock_create, patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock(return_value=["c1", "c2"])
    ) as mock_store, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "services.ingestion_pipeline.extract_text_with_metadata",
        new=AsyncMock(return_value=("hello world", [])),
    ) as mock_extract, patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    ):
        result = await pipeline.process_document(mock_file, tenant_id="dev")

    assert result["document_id"] == "doc123"
    assert result["chunks"] == 2
    assert result["status"] == "completed"
    assert result["status_endpoint"] == "/documents/doc123/status"

    mock_create.assert_awaited_once()
    mock_extract.assert_awaited_once()
    mock_store.assert_awaited_once()
    mock_cleanup.assert_not_awaited()

    statuses = [call.kwargs.get("status") for call in mock_update.await_args_list]
    assert statuses == [
        "uploaded",
        "extracting",
        "chunking",
        "embedding",
        "embedding",
        "storing",
        "completed",
    ]


@pytest.mark.asyncio
async def test_process_document_rejects_invalid_file_type():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "photo.png"
    mock_file.content_type = "image/png"
    mock_file.read = AsyncMock(return_value=b"\x89PNG")

    pipeline = IngestionPipeline(splitter_cls=_SingleChunkSplitter)

    with pytest.raises(UploadPipelineError) as excinfo:
        await pipeline.process_document(mock_file, tenant_id="dev")

    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "invalid_file_type"
    assert excinfo.value.stage == "validation"


def test_validate_file_accepts_charset_parameters_without_loosening_allowlist():
    pipeline = IngestionPipeline(splitter_cls=_SingleChunkSplitter)
    accepted = (
        ("text/plain; charset=utf-8", "notes.txt", b"hello"),
        ("text/html; charset=utf-8", "page.html", b"<p>hello</p>"),
        ("Text/Plain; charset=UTF-8", "notes.txt", b"hello"),
    )
    for content_type, filename, body in accepted:
        upload = AsyncMock(spec=UploadFile)
        upload.filename = filename
        upload.content_type = content_type
        pipeline.validate_file(upload, body)

    rejected = AsyncMock(spec=UploadFile)
    rejected.filename = "photo.png"
    rejected.content_type = "image/png; charset=binary"
    with pytest.raises(UploadPipelineError) as excinfo:
        pipeline.validate_file(rejected, b"\x89PNG")
    assert excinfo.value.code == "invalid_file_type"

    mismatched = AsyncMock(spec=UploadFile)
    mismatched.filename = "page.html"
    mismatched.content_type = "text/plain; charset=utf-8"
    with pytest.raises(UploadPipelineError) as mismatch_info:
        pipeline.validate_file(mismatched, b"hello")
    assert mismatch_info.value.code == "invalid_file_content"


@pytest.mark.asyncio
async def test_process_document_rejects_file_too_large(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "large.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"x" * 20)

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 5)
    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_MB", 0)

    pipeline = IngestionPipeline()

    with pytest.raises(UploadPipelineError) as excinfo:
        await pipeline.process_document(mock_file, tenant_id="dev")

    assert excinfo.value.status_code == 413
    assert excinfo.value.code == "file_too_large"
    assert excinfo.value.stage == "validation"


@pytest.mark.asyncio
async def test_process_document_marks_failed_when_no_text_extracted(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "empty.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"%PDF-fake-pdf-bytes")

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)

    pipeline = IngestionPipeline()

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc-no-text")), patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "services.ingestion_pipeline.extract_text_with_metadata",
        new=AsyncMock(return_value=("   ", [])),
    ):
        with pytest.raises(UploadPipelineError) as excinfo:
            await pipeline.process_document(mock_file, tenant_id="dev")

    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "no_text_extracted"
    assert excinfo.value.document_id == "doc-no-text"

    mock_cleanup.assert_awaited_once_with("doc-no-text", tenant_id="dev")
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "extracting"


@pytest.mark.asyncio
async def test_process_document_marks_failed_on_storage_error(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "store-fail.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"%PDF-fake-pdf-bytes")

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)

    pipeline = IngestionPipeline()

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc-store-fail")), patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "services.ingestion_pipeline.extract_text_with_metadata",
        new=AsyncMock(return_value=("hello world", [])),
    ), patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])
    ), patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock(side_effect=RuntimeError("db down"))
    ):
        with pytest.raises(UploadPipelineError) as excinfo:
            await pipeline.process_document(mock_file, tenant_id="dev")

    assert excinfo.value.status_code == 500
    assert excinfo.value.code == "upload_failed"
    assert excinfo.value.stage == "storing"
    assert excinfo.value.document_id == "doc-store-fail"

    mock_cleanup.assert_awaited_once_with("doc-store-fail", tenant_id="dev")
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "storing"

    assert mock_update.await_args_list[-1].kwargs["error"]["message"] == "An error occurred during document processing."
    assert "db down" not in mock_update.await_args_list[-1].kwargs["error"]["message"]

# ---------------------------------------------------------------------------
# Metadata generation unit tests (Issue #23)
# ---------------------------------------------------------------------------


def test_resolve_page_number_returns_none_for_empty_boundaries():
    assert _resolve_page_number(0, []) is None
    assert _resolve_page_number(999, []) is None


def test_resolve_page_number_single_page():
    boundaries = [PageBoundary(page_number=1, start_offset=0, end_offset=500)]
    assert _resolve_page_number(0, boundaries) == 1
    assert _resolve_page_number(499, boundaries) == 1


def test_resolve_page_number_multi_page():
    boundaries = [
        PageBoundary(page_number=1, start_offset=0, end_offset=100),
        PageBoundary(page_number=2, start_offset=100, end_offset=250),
        PageBoundary(page_number=3, start_offset=250, end_offset=400),
    ]
    assert _resolve_page_number(0, boundaries) == 1
    assert _resolve_page_number(99, boundaries) == 1
    assert _resolve_page_number(100, boundaries) == 2
    assert _resolve_page_number(249, boundaries) == 2
    assert _resolve_page_number(250, boundaries) == 3
    assert _resolve_page_number(399, boundaries) == 3


def test_build_chunk_records_populates_all_fields():
    docs = [_FakeDoc("hello world", 0), _FakeDoc("second chunk", 12)]
    embeddings = [[0.1, 0.2], [0.3, 0.4]]
    boundaries = [PageBoundary(page_number=1, start_offset=0, end_offset=100)]

    records = _build_chunk_records(docs, embeddings, boundaries)

    assert len(records) == 2

    assert records[0].chunk_text == "hello world"
    assert records[0].embedding == [0.1, 0.2]
    assert records[0].chunk_index == 0
    assert records[0].character_offset_start == 0
    assert records[0].character_offset_end == len("hello world")
    assert records[0].page_number == 1
    assert records[0].page_end == 1

    assert records[1].chunk_text == "second chunk"
    assert records[1].embedding == [0.3, 0.4]
    assert records[1].chunk_index == 1
    assert records[1].character_offset_start == 12
    assert records[1].character_offset_end == 12 + len("second chunk")
    assert records[1].page_number == 1
    assert records[1].page_end == 1


def test_build_chunk_records_page_number_none_for_txt():
    docs = [_FakeDoc("plain text", 0)]
    embeddings = [[0.5, 0.6]]

    records = _build_chunk_records(docs, embeddings, page_boundaries=[])

    assert records[0].page_number is None
    assert records[0].page_end is None


def test_resolve_page_span_single_page():
    boundaries = [
        PageBoundary(page_number=1, start_offset=0, end_offset=100),
        PageBoundary(page_number=2, start_offset=100, end_offset=200),
    ]
    assert _resolve_page_span(10, 50, boundaries) == (1, 1)


def test_resolve_page_span_two_pages():
    boundaries = [
        PageBoundary(page_number=1, start_offset=0, end_offset=100),
        PageBoundary(page_number=2, start_offset=100, end_offset=200),
    ]
    assert _resolve_page_span(80, 130, boundaries) == (1, 2)


def test_resolve_page_span_ends_on_next_page_boundary_without_including_it():
    boundaries = [
        PageBoundary(page_number=1, start_offset=0, end_offset=100),
        PageBoundary(page_number=2, start_offset=100, end_offset=200),
    ]
    assert _resolve_page_span(50, 100, boundaries) == (1, 1)


def test_build_chunk_records_two_page_pdf_span():
    page1 = "a" * 80
    page2 = "b" * 40
    text = page1 + page2
    boundaries = [
        PageBoundary(page_number=1, start_offset=0, end_offset=len(page1)),
        PageBoundary(page_number=2, start_offset=len(page1), end_offset=len(text)),
    ]
    span_text = text[70:110]
    docs = [_FakeDoc(span_text, 70)]
    records = _build_chunk_records(docs, [[0.1]], boundaries)
    assert records[0].page_number == 1
    assert records[0].page_end == 2


@pytest.mark.asyncio
async def test_process_document_passes_chunk_records_to_store(monkeypatch):
    """store_chunks_with_embeddings must receive ChunkRecord objects with metadata."""
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "report.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"%PDF-fake-pdf-bytes")

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_MB", 10)

    page_boundaries = [PageBoundary(page_number=1, start_offset=0, end_offset=20)]
    pipeline = IngestionPipeline(splitter_cls=_FixedSplitter)

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc-meta")), patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ), patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock(return_value=["c1", "c2"])
    ) as mock_store, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ), patch(
        "services.ingestion_pipeline.extract_text_with_metadata",
        new=AsyncMock(return_value=("hello world", page_boundaries)),
    ), patch(
        "services.ingestion_pipeline.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]]),
    ):
        await pipeline.process_document(mock_file, tenant_id="dev")

    mock_store.assert_awaited_once()
    _doc_id, records = mock_store.call_args.args
    assert _doc_id == "doc-meta"
    assert len(records) == 2
    assert all(isinstance(r, ChunkRecord) for r in records)

    assert records[0].chunk_index == 0
    assert records[0].character_offset_start == 0
    assert records[0].character_offset_end == len("chunk-a")
    assert records[0].page_number == 1

    assert records[1].chunk_index == 1
    assert records[1].character_offset_start == 7
    assert records[1].character_offset_end == 7 + len("chunk-b")


# ---------------------------------------------------------------------------
# Chunking strategy unit tests (Issue #125)
# ---------------------------------------------------------------------------


def test_fixed_chunking_strategy_matches_legacy_splitter_output():
    text = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda."

    legacy_splitter = RecursiveCharacterTextSplitter(
        chunk_size=18,
        chunk_overlap=4,
        add_start_index=True,
    )
    legacy_docs = legacy_splitter.create_documents([text])

    strategy = FixedChunkingStrategy(
        splitter_cls=RecursiveCharacterTextSplitter,
        chunk_size=18,
        chunk_overlap=4,
    )
    strategy_docs = strategy.chunk_text(text, metadata={"source": "unit-test"})

    assert _doc_snapshots(strategy_docs) == _doc_snapshots(legacy_docs)


def test_fixed_chunking_strategy_uses_splitter_with_expected_arguments():
    _TrackingSplitter.last_init = None
    _TrackingSplitter.last_create = None

    strategy = FixedChunkingStrategy(
        splitter_cls=_TrackingSplitter,
        chunk_size=11,
        chunk_overlap=3,
    )

    docs = strategy.chunk_text("hello world", metadata={"source": "tracking"})

    assert _TrackingSplitter.last_init == {
        "chunk_size": 11,
        "chunk_overlap": 3,
        "add_start_index": True,
    }
    assert _TrackingSplitter.last_create == {
        "texts": ["hello world"],
        "metadatas": [{"source": "tracking"}],
    }
    assert docs[0].metadata["source"] == "tracking"
    assert docs[0].metadata["start_index"] == 0


def test_paragraph_chunking_strategy_splits_on_paragraphs_and_tracks_headings():
    text = (
        "# Heading 1\n\n"
        "First paragraph lives here.\n\n"
        "Second paragraph is separate.\n\n"
        "# Heading 2\n\n"
        "Third paragraph belongs to the second heading."
    )

    strategy = ParagraphChunkingStrategy(
        splitter_cls=RecursiveCharacterTextSplitter,
        chunk_size=60,
        chunk_overlap=8,
    )
    docs = strategy.chunk_text(text, metadata={"source": "unit-test"})

    assert len(docs) == 3
    assert all(len(doc.page_content) <= 60 for doc in docs)

    assert docs[0].page_content.startswith("First paragraph")
    assert docs[0].metadata["heading"] == "Heading 1"
    assert docs[0].metadata["start_index"] == text.index("First paragraph")

    assert docs[1].page_content.startswith("Second paragraph")
    assert docs[1].metadata["heading"] == "Heading 1"
    assert docs[1].metadata["start_index"] == text.index("Second paragraph")

    assert docs[2].page_content.startswith("Third paragraph")
    assert docs[2].metadata["heading"] == "Heading 2"
    assert docs[2].metadata["start_index"] == text.index("Third paragraph")


def test_paragraph_chunking_strategy_splits_large_paragraphs_and_preserves_metadata():
    long_paragraph = "A" * 55
    text = f"# Heading 1\n\n{long_paragraph}"

    strategy = ParagraphChunkingStrategy(
        splitter_cls=RecursiveCharacterTextSplitter,
        chunk_size=20,
        chunk_overlap=5,
    )
    docs = strategy.chunk_text(text, metadata={"source": "unit-test"})

    assert len(docs) >= 3
    assert all(len(doc.page_content) <= 20 for doc in docs)
    assert all(doc.metadata["heading"] == "Heading 1" for doc in docs)
    assert docs[0].metadata["start_index"] == text.index(long_paragraph)
    assert docs[0].metadata["source"] == "unit-test"
    assert [doc.metadata["start_index"] for doc in docs] == sorted(
        doc.metadata["start_index"] for doc in docs
    )


def test_semantic_chunking_strategy_groups_sentences_and_overlaps():
    text = "# Topic\n\nSentence one. Sentence two. Sentence three."

    strategy = SemanticChunkingStrategy(
        splitter_cls=RecursiveCharacterTextSplitter,
        chunk_size=30,
        chunk_overlap=15,
    )
    docs = strategy.chunk_text(text, metadata={"source": "unit-test"})

    assert len(docs) == 2

    assert docs[0].page_content == "Sentence one. Sentence two."
    assert docs[0].metadata["heading"] == "Topic"
    assert docs[0].metadata["start_index"] == text.index("Sentence one.")

    assert docs[1].page_content == "Sentence two. Sentence three."
    assert docs[1].metadata["heading"] == "Topic"
    assert docs[1].metadata["start_index"] == text.index("Sentence two.")
    assert docs[1].page_content.startswith("Sentence two.")


def test_semantic_chunking_strategy_splits_large_sentences_and_preserves_metadata():
    long_sentence = f"{'A' * 45}."
    text = f"# Topic\n\n{long_sentence}"

    strategy = SemanticChunkingStrategy(
        splitter_cls=RecursiveCharacterTextSplitter,
        chunk_size=20,
        chunk_overlap=5,
    )
    docs = strategy.chunk_text(text, metadata={"source": "unit-test"})

    assert len(docs) >= 3
    assert all(len(doc.page_content) <= 20 for doc in docs)
    assert all(doc.metadata["heading"] == "Topic" for doc in docs)
    assert docs[0].metadata["start_index"] == text.index(long_sentence)
    assert docs[0].metadata["source"] == "unit-test"
    assert [doc.metadata["start_index"] for doc in docs] == sorted(
        doc.metadata["start_index"] for doc in docs
    )


def test_sanitize_filename_edge_cases():
    from services.ingestion_pipeline import _sanitize_filename
    assert _sanitize_filename("../../etc/passwd") == "passwd"
    assert _sanitize_filename("bad\nname\r\t.pdf") == "badname.pdf"
    assert _sanitize_filename("") == "upload"
    long_name = "a" * 300 + ".pdf"
    assert len(_sanitize_filename(long_name, max_length=255)) == 255

@pytest.mark.asyncio
async def test_validate_file_rejects_pdf_without_magic_bytes():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "report.pdf"
    mock_file.content_type = "application/pdf"
    pipeline = IngestionPipeline()
    
    with pytest.raises(UploadPipelineError) as excinfo:
        pipeline.validate_file(mock_file, b"definitely not a pdf bytes")
        
    assert excinfo.value.code == "invalid_file_content"

@pytest.mark.asyncio
async def test_validate_file_accepts_valid_cp1254_fallback():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "notes.txt"
    mock_file.content_type = "text/plain"
    pipeline = IngestionPipeline()
    pipeline.validate_file(mock_file, b"\xff\xfe")


@pytest.mark.asyncio
async def test_validate_file_rejects_markdown_mime_with_non_md_extension():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.content_type = "text/markdown"
    mock_file.filename = "notes.txt"
    pipeline = IngestionPipeline()

    with pytest.raises(UploadPipelineError) as excinfo:
        pipeline.validate_file(mock_file, b"# Title\n")

    assert excinfo.value.code == "invalid_file_content"


@pytest.mark.asyncio
async def test_validate_file_rejects_md_extension_with_plain_text_mime():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.content_type = "text/plain"
    mock_file.filename = "notes.md"
    pipeline = IngestionPipeline()

    with pytest.raises(UploadPipelineError) as excinfo:
        pipeline.validate_file(mock_file, b"# Title\n")

    assert excinfo.value.code == "invalid_file_content"


@pytest.mark.asyncio
async def test_process_document_markdown_ingests_to_completed(monkeypatch):
    md_bytes = b"# Markdown Ingest\n\nUnique fixture phrase alpha.\n"
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "guide.md"
    mock_file.content_type = "text/markdown"
    mock_file.read = AsyncMock(return_value=md_bytes)

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_MB", 10)

    pipeline = IngestionPipeline(splitter_cls=_TrackingSplitter)

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc-md")) as mock_create, patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock(return_value=["c1"])
    ) as mock_store, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ), patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])
    ):
        result = await pipeline.process_document(mock_file, tenant_id="dev")

    assert result["status"] == "completed"
    mock_create.assert_awaited_once()
    stored_records = mock_store.await_args.args[1]
    assert any("Unique fixture phrase alpha" in r.chunk_text for r in stored_records)
    assert "Markdown Ingest" in _TrackingSplitter.last_create["texts"][0]
    assert mock_update.await_args_list[-1].kwargs["status"] == "completed"


@pytest.mark.asyncio
async def test_corrupt_markdown_marks_document_failed_without_storing_chunks():
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
                doc_id="doc-md-fail",
                file_name="bad.md",
                content_type="text/markdown",
                file_bytes=b"# Broken\x00markdown",
                tenant_id="dev",
            )

    mock_store.assert_not_awaited()
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "extracting"


@pytest.mark.asyncio
async def test_validate_file_rejects_html_mime_with_non_html_extension():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.content_type = "text/html"
    mock_file.filename = "notes.txt"
    pipeline = IngestionPipeline()

    with pytest.raises(UploadPipelineError) as excinfo:
        pipeline.validate_file(mock_file, b"<html><body>ok</body></html>")

    assert excinfo.value.code == "invalid_file_content"


@pytest.mark.asyncio
async def test_validate_file_rejects_html_extension_with_plain_text_mime():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.content_type = "text/plain"
    mock_file.filename = "page.html"
    pipeline = IngestionPipeline()

    with pytest.raises(UploadPipelineError) as excinfo:
        pipeline.validate_file(mock_file, b"<html><body>ok</body></html>")

    assert excinfo.value.code == "invalid_file_content"


@pytest.mark.asyncio
async def test_process_document_html_ingests_to_completed(monkeypatch):
    html_bytes = b"""<!DOCTYPE html><html><body>
<h1>HTML Pipeline Ingest</h1>
<p>Unique HTML pipeline phrase beta.</p>
<script>ignored();</script>
</body></html>"""
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "page.html"
    mock_file.content_type = "text/html"
    mock_file.read = AsyncMock(return_value=html_bytes)

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_MB", 10)

    pipeline = IngestionPipeline(splitter_cls=_TrackingSplitter)

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc-html")) as mock_create, patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock(return_value=["c1"])
    ) as mock_store, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ), patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])
    ):
        result = await pipeline.process_document(mock_file, tenant_id="dev")

    assert result["status"] == "completed"
    mock_create.assert_awaited_once()
    stored_records = mock_store.await_args.args[1]
    assert any("Unique HTML pipeline phrase beta" in r.chunk_text for r in stored_records)
    assert "HTML Pipeline Ingest" in _TrackingSplitter.last_create["texts"][0]
    assert "ignored" not in _TrackingSplitter.last_create["texts"][0]
    assert mock_update.await_args_list[-1].kwargs["status"] == "completed"


@pytest.mark.asyncio
async def test_validate_file_rejects_docx_mime_with_non_docx_extension():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_file.filename = "notes.txt"
    pipeline = IngestionPipeline()

    docx_bytes = build_minimal_docx(paragraphs=["ok"])
    with pytest.raises(UploadPipelineError) as excinfo:
        pipeline.validate_file(mock_file, docx_bytes)

    assert excinfo.value.code == "invalid_file_content"


@pytest.mark.asyncio
async def test_validate_file_rejects_docx_extension_with_plain_text_mime():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.content_type = "text/plain"
    mock_file.filename = "notes.docx"
    pipeline = IngestionPipeline()

    docx_bytes = build_minimal_docx(paragraphs=["ok"])
    with pytest.raises(UploadPipelineError) as excinfo:
        pipeline.validate_file(mock_file, docx_bytes)

    assert excinfo.value.code == "invalid_file_content"


@pytest.mark.asyncio
async def test_process_document_docx_ingests_to_completed(monkeypatch):
    docx_bytes = build_minimal_docx(
        paragraphs=["DOCX Pipeline Ingest", "Unique DOCX pipeline phrase omega."],
        table_rows=[["Table cell north", "Table cell south"]],
    )
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "report.docx"
    mock_file.content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    mock_file.read = AsyncMock(return_value=docx_bytes)

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_MB", 10)

    pipeline = IngestionPipeline(splitter_cls=_TrackingSplitter)

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc-docx")) as mock_create, patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock(return_value=["c1"])
    ) as mock_store, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ), patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])
    ):
        result = await pipeline.process_document(mock_file, tenant_id="dev")

    assert result["status"] == "completed"
    mock_create.assert_awaited_once()
    stored_records = mock_store.await_args.args[1]
    assert any("Unique DOCX pipeline phrase omega." in r.chunk_text for r in stored_records)
    chunked_text = _TrackingSplitter.last_create["texts"][0]
    assert "Table cell north" in chunked_text
    assert "Table cell north\tTable cell south" in chunked_text
    assert mock_update.await_args_list[-1].kwargs["status"] == "completed"


@pytest.mark.asyncio
async def test_corrupt_docx_marks_document_failed_without_storing_chunks():
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
                doc_id="doc-docx-fail",
                file_name="bad.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                file_bytes=b"PK\x03\x04corrupt",
                tenant_id="dev",
            )

    mock_store.assert_not_awaited()
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "extracting"


@pytest.mark.asyncio
async def test_encrypted_docx_marks_document_failed_without_storing_chunks():
    pipeline = IngestionPipeline()
    encrypted = build_encrypted_docx_stub()

    with patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ), patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock()
    ) as mock_store:
        with pytest.raises(DocumentExtractionError, match="Encrypted DOCX"):
            await pipeline.process_document_background(
                doc_id="doc-docx-encrypted",
                file_name="locked.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                file_bytes=encrypted,
                tenant_id="dev",
            )

    mock_store.assert_not_awaited()
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"


@pytest.mark.asyncio
async def test_process_document_rejects_pptx_at_validation():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "slides.pptx"
    mock_file.content_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    mock_file.read = AsyncMock(return_value=b"PK\x03\x04")

    pipeline = IngestionPipeline(splitter_cls=_SingleChunkSplitter)

    with pytest.raises(UploadPipelineError) as excinfo:
        await pipeline.process_document(mock_file, tenant_id="dev")

    assert excinfo.value.code == "invalid_file_type"


@pytest.mark.asyncio
async def test_corrupt_html_marks_document_failed_without_storing_chunks():
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
                doc_id="doc-html-fail",
                file_name="bad.html",
                content_type="text/html",
                file_bytes=b"<html>\x00<body></body></html>",
                tenant_id="dev",
            )

    mock_store.assert_not_awaited()
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "extracting"


# ---------------------------------------------------------------------------
# Error classification unit tests (Issue #394)
# ---------------------------------------------------------------------------


def test_classify_ingestion_error_maps_provider_auth_error():
    from services.providers.base import ProviderAuthError

    result = _classify_ingestion_error(ProviderAuthError("401: invalid key"), "embedding")
    assert result["code"] == "embedding_invalid_api_key"
    assert result["stage"] == "embedding"
    assert "401" not in result["message"]
    assert "invalid key" not in result["message"]


def test_classify_ingestion_error_maps_provider_rate_limit_error():
    from services.providers.base import ProviderRateLimitError

    result = _classify_ingestion_error(ProviderRateLimitError("429: rate limited"), "embedding")
    assert result["code"] == "embedding_rate_limited"
    assert result["stage"] == "embedding"
    assert "429" not in result["message"]


def test_classify_ingestion_error_maps_provider_connection_error():
    from services.providers.base import ProviderConnectionError

    result = _classify_ingestion_error(ProviderConnectionError("Connection refused"), "embedding")
    assert result["code"] == "provider_unreachable"
    assert result["stage"] == "embedding"
    assert "Connection refused" not in result["message"]


def test_classify_ingestion_error_maps_provider_timeout_error():
    from services.providers.base import ProviderTimeoutError

    result = _classify_ingestion_error(ProviderTimeoutError("Request timed out"), "embedding")
    assert result["code"] == "provider_timeout"
    assert result["stage"] == "embedding"
    assert "Request timed out" not in result["message"]


def test_classify_ingestion_error_falls_back_for_unknown_exception():
    result = _classify_ingestion_error(RuntimeError("something unexpected"), "storing")
    assert result["code"] == "pipeline_error"
    assert result["stage"] == "storing"
    assert result["message"] == "An error occurred during document processing."
    assert "something unexpected" not in result["message"]


def test_classify_ingestion_error_preserves_upload_pipeline_error_fields():
    exc = UploadPipelineError(
        status_code=422,
        code="no_text_extracted",
        stage="extracting",
        message="No extractable text was found in the uploaded document.",
    )
    result = _classify_ingestion_error(exc, "extracting")
    assert result["code"] == "no_text_extracted"
    assert result["stage"] == "extracting"
    assert result["message"] == "No extractable text was found in the uploaded document."


@pytest.mark.asyncio
async def test_process_document_background_updates_chunk_progress_during_embedding():
    pipeline = IngestionPipeline(splitter_cls=_ManyChunkSplitter)
    embed_batch_sizes: list[int] = []

    async def fake_get_embeddings(texts: list[str], **kwargs) -> list[list[float]]:
        embed_batch_sizes.append(len(texts))
        return [[0.1, 0.2] for _ in texts]

    with patch("services.ingestion_pipeline.db.update_document_status", new=AsyncMock()) as mock_update, patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings",
        new=AsyncMock(return_value=[f"c{i}" for i in range(25)]),
    ), patch(
        "services.ingestion_pipeline.extract_text_with_metadata",
        new=AsyncMock(return_value=("hello world", [])),
    ), patch(
        "services.ingestion_pipeline.get_embeddings",
        side_effect=fake_get_embeddings,
    ):
        await pipeline.process_document_background(
            doc_id="doc-progress",
            file_name="test.pdf",
            content_type="application/pdf",
            file_bytes=b"%PDF-fake",
            tenant_id="dev",
        )

    assert embed_batch_sizes == [10, 10, 5]

    embedding_updates = [
        call.kwargs.get("chunks")
        for call in mock_update.await_args_list
        if call.kwargs.get("status") == "embedding" and call.kwargs.get("chunks") is not None
    ]
    assert embedding_updates == [
        {"total": 25, "processed": 0},
        {"total": 25, "processed": 10},
        {"total": 25, "processed": 20},
        {"total": 25, "processed": 25},
    ]


@pytest.mark.asyncio
async def test_process_document_background_auth_error_sets_structured_code():
    from services.providers.base import ProviderAuthError

    pipeline = IngestionPipeline(splitter_cls=_SingleChunkSplitter)

    with patch("services.ingestion_pipeline.db.update_document_status", new=AsyncMock()) as mock_update, \
         patch("services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()), \
         patch(
             "services.ingestion_pipeline.extract_text_with_metadata",
             new=AsyncMock(return_value=("hello world", [])),
         ), \
         patch(
             "services.ingestion_pipeline.get_embeddings",
             new=AsyncMock(side_effect=ProviderAuthError("401: invalid key")),
         ):

        with pytest.raises(ProviderAuthError):
            await pipeline.process_document_background(
                doc_id="doc-auth",
                file_name="test.pdf",
                content_type="application/pdf",
                file_bytes=b"%PDF-fake",
                tenant_id="dev",
            )

    error = mock_update.await_args_list[-1].kwargs["error"]
    assert error["code"] == "embedding_invalid_api_key"
    assert error["stage"] == "embedding"
    assert "401" not in error["message"]
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"


@pytest.mark.asyncio
async def test_process_document_background_rate_limit_sets_structured_code(monkeypatch):
    from services.providers.base import ProviderRateLimitError

    # Rate limits are retryable. The structured code is stored once retries
    # are exhausted, not on the first attempt.
    monkeypatch.setattr(
        "services.ingestion_outcome.config.QUEUE_JOB_MAX_RETRIES", 0
    )

    pipeline = IngestionPipeline(splitter_cls=_SingleChunkSplitter)

    with patch("services.ingestion_pipeline.db.update_document_status", new=AsyncMock()) as mock_update, \
         patch("services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()), \
         patch(
             "services.ingestion_pipeline.extract_text_with_metadata",
             new=AsyncMock(return_value=("hello world", [])),
         ), \
         patch(
             "services.ingestion_pipeline.get_embeddings",
             new=AsyncMock(side_effect=ProviderRateLimitError("429: quota exceeded")),
         ):

        with pytest.raises(ProviderRateLimitError):
            await pipeline.process_document_background(
                doc_id="doc-rate",
                file_name="test.pdf",
                content_type="application/pdf",
                file_bytes=b"%PDF-fake",
                tenant_id="dev",
            )

    error = mock_update.await_args_list[-1].kwargs["error"]
    assert error["code"] == "embedding_rate_limited"
    assert error["stage"] == "embedding"
    assert "429" not in error["message"]
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"


@pytest.mark.asyncio
async def test_process_document_background_unknown_exception_falls_back_to_generic():
    pipeline = IngestionPipeline(splitter_cls=_SingleChunkSplitter)

    with patch("services.ingestion_pipeline.db.update_document_status", new=AsyncMock()) as mock_update, \
         patch("services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()), \
         patch(
             "services.ingestion_pipeline.extract_text_with_metadata",
             new=AsyncMock(return_value=("hello world", [])),
         ), \
         patch(
             "services.ingestion_pipeline.get_embeddings",
             new=AsyncMock(side_effect=RuntimeError("unexpected internal error")),
         ):

        with pytest.raises(RuntimeError):
            await pipeline.process_document_background(
                doc_id="doc-unknown",
                file_name="test.pdf",
                content_type="application/pdf",
                file_bytes=b"%PDF-fake",
                tenant_id="dev",
            )

    error = mock_update.await_args_list[-1].kwargs["error"]
    assert error["code"] == "pipeline_error"
    assert error["stage"] == "embedding"
    assert error["message"] == "An error occurred during document processing."
    assert "unexpected internal error" not in error["message"]
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"


# ---------------------------------------------------------------------------
# Cleaning + chunking integration (paragraph preservation, page provenance)
# ---------------------------------------------------------------------------


class _FakeLangChainDoc:
    def __init__(self, text: str, start_index: int):
        self.page_content = text
        self.metadata = {"start_index": start_index}


def _chunk_records_for_text(
    cleaned_text: str,
    chunk_text: str,
    page_boundaries: list[PageBoundary],
) -> list[ChunkRecord]:
    start = cleaned_text.index(chunk_text)
    docs = [_FakeLangChainDoc(chunk_text, start)]
    return _build_chunk_records(docs, [[0.1]], page_boundaries)


def test_clean_text_and_paragraph_chunking_preserves_heading_and_paragraphs():
    raw = "# Heading\n\nFirst paragraph.\n\nSecond paragraph."
    from services.text_cleaning_service import clean_text

    cleaned = clean_text(raw)
    strategy = ParagraphChunkingStrategy(
        splitter_cls=RecursiveCharacterTextSplitter,
        chunk_size=200,
        chunk_overlap=8,
    )
    docs = strategy.chunk_text(cleaned, metadata={"source": "integration-test"})

    assert len(docs) == 2
    assert docs[0].page_content.strip() == "First paragraph."
    assert docs[0].metadata["heading"] == "Heading"
    assert docs[1].page_content.strip() == "Second paragraph."
    assert docs[1].metadata["heading"] == "Heading"


def test_clean_text_and_paragraph_chunking_preserves_plain_paragraphs():
    raw = "Paragraph one.\n\nParagraph two."
    from services.text_cleaning_service import clean_text

    cleaned = clean_text(raw)
    strategy = ParagraphChunkingStrategy(
        splitter_cls=RecursiveCharacterTextSplitter,
        chunk_size=200,
        chunk_overlap=8,
    )
    docs = strategy.chunk_text(cleaned)

    assert len(docs) == 2
    assert docs[0].page_content.strip() == "Paragraph one."
    assert docs[1].page_content.strip() == "Paragraph two."


def test_prepare_extracted_document_resolves_conclusion_on_page_two_after_shrinkage():
    from services.extraction_service import prepare_extracted_document_for_chunking

    page1 = "Intro\n\n\n\n\n\n\n\n"
    page2 = "Conclusion on page two.\n"
    raw = page1 + page2
    raw_boundaries = [
        PageBoundary(page_number=1, start_offset=0, end_offset=len(page1)),
        PageBoundary(page_number=2, start_offset=len(page1), end_offset=len(raw)),
    ]

    cleaned, boundaries = prepare_extracted_document_for_chunking(raw, raw_boundaries)
    chunk_text = "Conclusion on page two."
    records = _chunk_records_for_text(cleaned, chunk_text, boundaries)

    assert records[0].page_number == 2
    assert records[0].character_offset_start == cleaned.index(chunk_text)


def test_prepare_extracted_document_keeps_expanded_page_one_content_on_page_one():
    from services.extraction_service import prepare_extracted_document_for_chunking

    page1 = "ﬁ" * 20 + "\n"
    page2 = "Z\n"
    raw = page1 + page2
    raw_boundaries = [
        PageBoundary(page_number=1, start_offset=0, end_offset=len(page1)),
        PageBoundary(page_number=2, start_offset=len(page1), end_offset=len(raw)),
    ]

    cleaned, boundaries = prepare_extracted_document_for_chunking(raw, raw_boundaries)
    # Offset 30 is still within the expanded ligature run on page 1.
    assert cleaned[30:32] == "fi"
    assert _resolve_page_number(30, boundaries) == 1


def test_prepare_extracted_document_boundary_offset_resolves_to_later_page():
    from services.extraction_service import prepare_extracted_document_for_chunking

    page1 = "Page one text.\n"
    page2 = "Page two text.\n"
    raw = page1 + page2
    raw_boundaries = [
        PageBoundary(page_number=1, start_offset=0, end_offset=len(page1)),
        PageBoundary(page_number=2, start_offset=len(page1), end_offset=len(raw)),
    ]

    cleaned, boundaries = prepare_extracted_document_for_chunking(raw, raw_boundaries)
    page_two_start = boundaries[1].start_offset

    assert _resolve_page_number(page_two_start, boundaries) == 2
    assert _resolve_page_number(page_two_start - 1, boundaries) == 1


def test_prepare_extracted_document_txt_leaves_page_boundaries_empty():
    from services.extraction_service import prepare_extracted_document_for_chunking

    cleaned, boundaries = prepare_extracted_document_for_chunking(
        "Paragraph one.\n\nParagraph two.",
        [],
    )

    assert boundaries == []
    assert cleaned == "Paragraph one.\n\nParagraph two."
    assert _resolve_page_number(0, boundaries) is None
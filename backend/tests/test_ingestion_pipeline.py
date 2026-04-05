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
from services.ingestion_pipeline import (
    FixedChunkingStrategy,
    IngestionPipeline,
    ParagraphChunkingStrategy,
    RecursiveCharacterTextSplitter,
    SemanticChunkingStrategy,
    UploadPipelineError,
    _build_chunk_records,
    _resolve_page_number,
)
from services.extraction_service import PageBoundary


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
        result = await pipeline.process_document(mock_file)

    assert result["document_id"] == "doc123"
    assert result["chunks"] == 2
    assert result["status"] == "completed"
    assert result["status_endpoint"] == "/documents/doc123/status"

    mock_create.assert_awaited_once()
    mock_extract.assert_awaited_once()
    mock_store.assert_awaited_once()
    mock_cleanup.assert_not_awaited()

    statuses = [call.kwargs.get("status") for call in mock_update.await_args_list]
    assert statuses == ["uploaded", "extracting", "chunking", "embedding", "storing", "completed"]


@pytest.mark.asyncio
async def test_process_document_rejects_invalid_file_type():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "bad.docx"
    mock_file.content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_file.read = AsyncMock(return_value=b"x")

    pipeline = IngestionPipeline(splitter_cls=_SingleChunkSplitter)

    with pytest.raises(UploadPipelineError) as excinfo:
        await pipeline.process_document(mock_file)

    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "invalid_file_type"
    assert excinfo.value.stage == "validation"


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
        await pipeline.process_document(mock_file)

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
            await pipeline.process_document(mock_file)

    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "no_text_extracted"
    assert excinfo.value.document_id == "doc-no-text"

    mock_cleanup.assert_awaited_once_with("doc-no-text")
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
            await pipeline.process_document(mock_file)

    assert excinfo.value.status_code == 500
    assert excinfo.value.code == "upload_failed"
    assert excinfo.value.stage == "storing"
    assert excinfo.value.document_id == "doc-store-fail"

    mock_cleanup.assert_awaited_once_with("doc-store-fail")
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "storing"


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

    assert records[1].chunk_text == "second chunk"
    assert records[1].embedding == [0.3, 0.4]
    assert records[1].chunk_index == 1
    assert records[1].character_offset_start == 12
    assert records[1].character_offset_end == 12 + len("second chunk")
    assert records[1].page_number == 1


def test_build_chunk_records_page_number_none_for_txt():
    docs = [_FakeDoc("plain text", 0)]
    embeddings = [[0.5, 0.6]]

    records = _build_chunk_records(docs, embeddings, page_boundaries=[])

    assert records[0].page_number is None


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
        await pipeline.process_document(mock_file)

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

from abc import ABC, abstractmethod
import bisect
import logging
import pathlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

try:
    import nltk
    from nltk.tokenize import sent_tokenize
except ImportError:  # pragma: no cover - optional dependency in some test envs
    nltk = None
    sent_tokenize = None

from fastapi import UploadFile

try:
    from langchain_core.documents import Document as _LangChainDocument
except ImportError:  # pragma: no cover - lightweight fallback for constrained envs
    @dataclass
    class _LangChainDocument:
        page_content: str
        metadata: dict[str, Any]


try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - lightweight fallback for constrained envs
    class RecursiveCharacterTextSplitter:
        def __init__(
            self,
            chunk_size: int,
            chunk_overlap: int,
            add_start_index: bool = False,
        ) -> None:
            self.chunk_size = chunk_size
            self.chunk_overlap = chunk_overlap
            self.add_start_index = add_start_index

        def create_documents(
            self,
            texts: list[str],
            metadatas: list[dict[str, Any]] | None = None,
        ) -> list[_LangChainDocument]:
            docs: list[_LangChainDocument] = []
            metadatas = metadatas or [{} for _ in texts]
            step = max(1, self.chunk_size - self.chunk_overlap)

            for text, base_metadata in zip(texts, metadatas):
                if not text:
                    continue

                start = 0
                while start < len(text):
                    end = min(len(text), start + self.chunk_size)
                    metadata = dict(base_metadata)
                    if self.add_start_index:
                        metadata["start_index"] = start
                    docs.append(
                        _LangChainDocument(
                            page_content=text[start:end],
                            metadata=metadata,
                        )
                    )
                    if end >= len(text):
                        break
                    start += step

            return docs


import db
from core.config import config
from db.base import ChunkRecord
from services.embedding_service import get_embeddings
from services.extraction_service import PageBoundary, extract_text_with_metadata
from services.text_cleaning_service import clean_text

logger = logging.getLogger(__name__)

ALLOWED_UPLOAD_TYPES = {"application/pdf", "text/plain"}
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(?P<heading>.+?)\s*$")
FALLBACK_SENTENCE_PATTERN = re.compile(r".+?(?:[.!?](?=\s+|$)|$)", re.DOTALL)

if TYPE_CHECKING:
    from langchain_core.documents import Document as LangChainDocument
else:
    LangChainDocument = _LangChainDocument


@dataclass
class _TextBlock:
    text: str
    start_index: int
    heading: str | None = None


@dataclass
class _SentenceSpan:
    start_index: int
    end_index: int


def _create_document(
    page_content: str,
    metadata: dict[str, Any],
) -> LangChainDocument:
    return _LangChainDocument(page_content=page_content, metadata=metadata)


def _merge_metadata(
    base_metadata: dict[str, Any] | None = None,
    *,
    start_index: int | None = None,
    heading: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(base_metadata or {})
    if extra_metadata:
        metadata.update(extra_metadata)
    if start_index is not None:
        metadata["start_index"] = start_index
    if heading is not None:
        metadata["heading"] = heading
    return metadata


def _extract_heading(line: str) -> str | None:
    match = HEADING_PATTERN.match(line)
    if not match:
        return None
    return match.group("heading").strip()


def _is_heading_only_block(block_text: str) -> bool:
    non_empty_lines = [line for line in block_text.splitlines() if line.strip()]
    return len(non_empty_lines) == 1 and _extract_heading(non_empty_lines[0]) is not None


def _iter_text_blocks(text: str) -> list[_TextBlock]:
    """
    Split text on blank lines while honoring markdown heading boundaries.

    Heading-only blocks are treated as metadata boundaries for following chunks
    rather than standalone chunks.
    """
    blocks: list[_TextBlock] = []
    current_heading: str | None = None
    current_parts: list[str] = []
    current_start: int | None = None
    cursor = 0

    def flush_current_block() -> None:
        nonlocal current_parts, current_start
        if current_start is None:
            current_parts = []
            return

        block_text = "".join(current_parts)
        if block_text.strip():
            if not _is_heading_only_block(block_text):
                blocks.append(
                    _TextBlock(
                        text=block_text,
                        start_index=current_start,
                        heading=current_heading,
                    )
                )
        current_parts = []
        current_start = None

    for line in text.splitlines(keepends=True):
        line_start = cursor
        cursor += len(line)
        heading = _extract_heading(line.rstrip("\r\n"))

        if heading is not None:
            flush_current_block()
            current_heading = heading
            current_start = line_start
            current_parts = [line]
            continue

        if not line.strip():
            flush_current_block()
            continue

        if current_start is None:
            current_start = line_start
        current_parts.append(line)

    flush_current_block()
    return blocks


def _split_with_recursive_splitter(
    splitter_cls,
    text: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    metadata: dict[str, Any] | None = None,
) -> list[LangChainDocument]:
    splitter = splitter_cls(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )

    try:
        raw_docs = splitter.create_documents([text], metadatas=[dict(metadata or {})])
    except TypeError:
        raw_docs = splitter.create_documents([text])

    documents: list[LangChainDocument] = []
    for doc in raw_docs:
        doc_metadata = _merge_metadata(
            metadata,
            extra_metadata=dict(getattr(doc, "metadata", {}) or {}),
        )
        documents.append(
            _create_document(
                page_content=doc.page_content,
                metadata=doc_metadata,
            )
        )
    return documents


def _rebase_documents(
    docs: list[LangChainDocument],
    *,
    base_start_index: int,
    base_metadata: dict[str, Any] | None = None,
    heading: str | None = None,
) -> list[LangChainDocument]:
    rebased_docs: list[LangChainDocument] = []
    for doc in docs:
        relative_start = int(getattr(doc, "metadata", {}).get("start_index", 0))
        rebased_docs.append(
            _create_document(
                page_content=doc.page_content,
                metadata=_merge_metadata(
                    base_metadata,
                    start_index=base_start_index + relative_start,
                    heading=heading,
                    extra_metadata=dict(getattr(doc, "metadata", {}) or {}),
                ),
            )
        )
    return rebased_docs


def _ensure_sentence_tokenizer() -> bool:
    if nltk is None or sent_tokenize is None:
        return False

    try:
        nltk.data.find("tokenizers/punkt")
        return True
    except LookupError:
        pass

    for package_name in ("punkt", "punkt_tab"):
        try:
            nltk.download(package_name, quiet=True)
        except Exception as exc:  # pragma: no cover - depends on local env/network
            logger.warning(f"Failed to download NLTK package {package_name}: {exc}")

    try:
        nltk.data.find("tokenizers/punkt")
        return True
    except LookupError:
        logger.warning("NLTK punkt tokenizer unavailable; falling back to regex sentence splitting.")
        return False


def _sentence_spans_from_regex(text: str) -> list[_SentenceSpan]:
    spans: list[_SentenceSpan] = []
    for match in FALLBACK_SENTENCE_PATTERN.finditer(text):
        candidate = match.group(0)
        if not candidate.strip():
            continue
        trimmed_leading = len(candidate) - len(candidate.lstrip())
        trimmed_trailing = len(candidate) - len(candidate.rstrip())
        start = match.start() + trimmed_leading
        end = match.end() - trimmed_trailing
        if start < end:
            spans.append(_SentenceSpan(start_index=start, end_index=end))
    return spans


def _sentence_spans_from_nltk(text: str) -> list[_SentenceSpan]:
    spans: list[_SentenceSpan] = []
    cursor = 0

    for sentence in sent_tokenize(text):
        if not sentence.strip():
            continue

        start = text.find(sentence, cursor)
        sentence_text = sentence

        if start < 0:
            sentence_text = sentence.strip()
            start = text.find(sentence_text, cursor)

        if start < 0:
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            start = cursor
            sentence_text = sentence.strip()

        end = start + len(sentence_text)
        spans.append(_SentenceSpan(start_index=start, end_index=end))
        cursor = end

    return spans


def _sentence_spans(text: str) -> list[_SentenceSpan]:
    if not text.strip():
        return []

    if _ensure_sentence_tokenizer():
        spans = _sentence_spans_from_nltk(text)
        if spans:
            return spans

    return _sentence_spans_from_regex(text)


class ChunkingStrategy(ABC):
    """Common interface for document chunking implementations."""

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> None:
        self.chunk_size = chunk_size if chunk_size is not None else config.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap if chunk_overlap is not None else config.CHUNK_OVERLAP

    @abstractmethod
    def chunk_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[LangChainDocument]:
        """Return chunk documents with per-chunk metadata attached."""


class FixedChunkingStrategy(ChunkingStrategy):
    """Legacy fixed-size chunker implementation."""

    def __init__(
        self,
        splitter_cls=None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> None:
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._splitter_cls = splitter_cls or RecursiveCharacterTextSplitter

    def chunk_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[LangChainDocument]:
        return _split_with_recursive_splitter(
            self._splitter_cls,
            text,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            metadata=metadata,
        )


class ParagraphChunkingStrategy(ChunkingStrategy):
    """Paragraph- and heading-aware chunking."""

    def __init__(
        self,
        splitter_cls=None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> None:
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._splitter_cls = splitter_cls or RecursiveCharacterTextSplitter

    def chunk_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[LangChainDocument]:
        if not text.strip():
            return []

        documents: list[LangChainDocument] = []
        base_metadata = dict(metadata or {})

        for block in _iter_text_blocks(text):
            if len(block.text) <= self.chunk_size:
                documents.append(
                    _create_document(
                        page_content=block.text,
                        metadata=_merge_metadata(
                            base_metadata,
                            start_index=block.start_index,
                            heading=block.heading,
                        ),
                    )
                )
                continue

            split_docs = _split_with_recursive_splitter(
                self._splitter_cls,
                block.text,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                metadata=base_metadata,
            )
            documents.extend(
                _rebase_documents(
                    split_docs,
                    base_start_index=block.start_index,
                    base_metadata=base_metadata,
                    heading=block.heading,
                )
            )

        return documents


class SemanticChunkingStrategy(ChunkingStrategy):
    """Sentence-aware semantic chunking."""

    def __init__(
        self,
        splitter_cls=None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> None:
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._splitter_cls = splitter_cls or RecursiveCharacterTextSplitter

    def _next_start_index(
        self,
        spans: list[_SentenceSpan],
        chunk_start_idx: int,
        chunk_end_idx: int,
    ) -> int:
        if self.chunk_overlap <= 0:
            return chunk_end_idx + 1

        overlap_start_idx = chunk_end_idx
        while (
            overlap_start_idx > chunk_start_idx
            and spans[chunk_end_idx].end_index - spans[overlap_start_idx].start_index < self.chunk_overlap
        ):
            overlap_start_idx -= 1

        return max(chunk_start_idx + 1, overlap_start_idx)

    def _split_large_sentence(
        self,
        sentence_text: str,
        *,
        absolute_start_index: int,
        base_metadata: dict[str, Any],
        heading: str | None,
    ) -> list[LangChainDocument]:
        split_docs = _split_with_recursive_splitter(
            self._splitter_cls,
            sentence_text,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            metadata=base_metadata,
        )
        return _rebase_documents(
            split_docs,
            base_start_index=absolute_start_index,
            base_metadata=base_metadata,
            heading=heading,
        )

    def chunk_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[LangChainDocument]:
        if not text.strip():
            return []

        documents: list[LangChainDocument] = []
        base_metadata = dict(metadata or {})

        for block in _iter_text_blocks(text):
            spans = _sentence_spans(block.text)
            if not spans:
                documents.append(
                    _create_document(
                        page_content=block.text,
                        metadata=_merge_metadata(
                            base_metadata,
                            start_index=block.start_index,
                            heading=block.heading,
                        ),
                    )
                )
                continue

            sentence_idx = 0
            while sentence_idx < len(spans):
                first_span = spans[sentence_idx]
                if first_span.end_index - first_span.start_index > self.chunk_size:
                    sentence_text = block.text[first_span.start_index:first_span.end_index]
                    documents.extend(
                        self._split_large_sentence(
                            sentence_text,
                            absolute_start_index=block.start_index + first_span.start_index,
                            base_metadata=base_metadata,
                            heading=block.heading,
                        )
                    )
                    sentence_idx += 1
                    continue

                chunk_end_idx = sentence_idx
                chunk_start_offset = first_span.start_index
                chunk_end_offset = first_span.end_index

                while chunk_end_idx + 1 < len(spans):
                    next_span = spans[chunk_end_idx + 1]
                    candidate_length = next_span.end_index - chunk_start_offset
                    if candidate_length > self.chunk_size:
                        break
                    chunk_end_idx += 1
                    chunk_end_offset = next_span.end_index

                documents.append(
                    _create_document(
                        page_content=block.text[chunk_start_offset:chunk_end_offset],
                        metadata=_merge_metadata(
                            base_metadata,
                            start_index=block.start_index + chunk_start_offset,
                            heading=block.heading,
                        ),
                    )
                )

                if chunk_end_idx >= len(spans) - 1:
                    break

                sentence_idx = self._next_start_index(spans, sentence_idx, chunk_end_idx)

        return documents


def build_chunking_strategy(
    strategy_name: str | None = None,
    splitter_cls=None,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> ChunkingStrategy:
    """Resolve a configured strategy name to a concrete chunking implementation."""
    selected_strategy = (strategy_name or config.CHUNKING_STRATEGY).strip().lower()

    if selected_strategy == "fixed":
        return FixedChunkingStrategy(
            splitter_cls=splitter_cls,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    if selected_strategy == "paragraph":
        return ParagraphChunkingStrategy(
            splitter_cls=splitter_cls,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    if selected_strategy == "semantic":
        return SemanticChunkingStrategy(
            splitter_cls=splitter_cls,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    raise ValueError(f"Unsupported chunking strategy: {selected_strategy}")


def _resolve_page_number(
    offset: int,
    page_boundaries: list[PageBoundary],
) -> int | None:
    """
    Return the 1-based page number that contains *offset*, or None for non-PDF.

    Uses binary search on the sorted start_offset values for O(log n) lookup.
    """
    if not page_boundaries:
        return None
    starts = [pb.start_offset for pb in page_boundaries]
    idx = bisect.bisect_right(starts, offset) - 1
    idx = max(0, idx)
    return page_boundaries[idx].page_number


def _build_chunk_records(
    langchain_docs: list,
    embeddings: list[list[float]],
    page_boundaries: list[PageBoundary],
) -> list[ChunkRecord]:
    """
    Pair langchain Document objects (which carry start_index metadata) with
    their embeddings and compute all chunk metadata fields.
    """
    records: list[ChunkRecord] = []
    for chunk_index, (doc, embedding) in enumerate(zip(langchain_docs, embeddings)):
        start = doc.metadata.get("start_index", 0)
        end = start + len(doc.page_content)
        records.append(
            ChunkRecord(
                chunk_text=doc.page_content,
                embedding=embedding,
                chunk_index=chunk_index,
                character_offset_start=start,
                character_offset_end=end,
                page_number=_resolve_page_number(start, page_boundaries),
            )
        )
    return records


@dataclass
class _FileMetadata:
    """Minimal duck-type shim used by extract_text_from_file for background jobs."""

    content_type: str
    filename: str

def _sanitize_filename(name: str, max_length: int = 255) -> str:
    name = pathlib.Path(name).name  # strip path components
    name = re.sub(r"[^\w\s\-.]", "", name)  # strip control/special chars
    name = name.strip()[:max_length]
    return name or "upload"
class UploadPipelineError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        stage: str,
        message: str,
        document_id: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.stage = stage
        self.message = message
        self.document_id = document_id


class IngestionPipeline:
    def __init__(self, splitter_cls=None):
        self._splitter_cls = splitter_cls or RecursiveCharacterTextSplitter

    def _build_chunking_strategy(self, strategy_name: str | None = None) -> ChunkingStrategy:
        return build_chunking_strategy(
            strategy_name=strategy_name,
            splitter_cls=self._splitter_cls,
        )

    def _build_base_chunk_metadata(
        self,
        *,
        file_name: str,
        content_type: str,
    ) -> dict[str, Any]:
        return {
            "file_name": file_name,
            "content_type": content_type,
        }

    def _chunk_document_text(
        self,
        text: str,
        *,
        file_name: str,
        content_type: str,
    ) -> list[LangChainDocument]:
        strategy = self._build_chunking_strategy()
        base_metadata = self._build_base_chunk_metadata(
            file_name=file_name,
            content_type=content_type,
        )
        return strategy.chunk_text(text, metadata=base_metadata)

    def validate_file(self, file: UploadFile, file_bytes: bytes) -> None:
        stage = "validation"

        if file.content_type not in ALLOWED_UPLOAD_TYPES:
            raise UploadPipelineError(
                status_code=400,
                code="invalid_file_type",
                stage=stage,
                message="Only PDF and TXT files are supported.",
            )

        if not file_bytes:
            raise UploadPipelineError(
                status_code=400,
                code="empty_file",
                stage=stage,
                message="Uploaded file is empty.",
            )

        if len(file_bytes) > config.MAX_UPLOAD_SIZE_BYTES:
            raise UploadPipelineError(
                status_code=413,
                code="file_too_large",
                stage=stage,
                message=(
                    f"File exceeds maximum upload size of {config.MAX_UPLOAD_SIZE_MB} MB."
                ),
            )

        if file.content_type == "application/pdf" and not file_bytes.startswith(b"%PDF-"):
            raise UploadPipelineError(
                status_code=400,
                code="invalid_file_content",
                stage=stage,
                message="File content does not match the declared PDF type.",
            )

        if file.content_type == "text/plain":
            try:
                file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raise UploadPipelineError(
                    status_code=400,
                    code="invalid_file_content",
                    stage=stage,
                    message="File content is not valid UTF-8 text.",
                )

    async def _update_status(
        self,
        doc_id: str,
        status: str,
        error: dict | None = None,
        chunks: dict | None = None,
    ) -> None:
        await db.update_document_status(
            doc_id=doc_id,
            status=status,
            error=error,
            chunks=chunks,
        )

    async def _handle_error(self, doc_id: str, stage: str, message: str) -> None:
        safe_message = message[:500]
        try:
            await self._update_status(
                doc_id=doc_id,
                status="failed",
                error={"stage": stage, "message": safe_message},
            )
        except Exception as status_error:
            logger.error(f"Failed to mark document {doc_id} as failed: {status_error}")

        try:
            await db.delete_document_chunks(doc_id)
        except Exception as cleanup_error:
            logger.error(f"Failed to cleanup chunks for document {doc_id}: {cleanup_error}")

    async def process_document(self, file: UploadFile) -> dict:
        safe_filename = _sanitize_filename(file.filename or "")
        logger.info(f"Starting upload for file: {safe_filename} ({file.content_type})")

        doc_id: str | None = None
        stage = "validation"

        try:
            file_bytes = await file.read()
            self.validate_file(file, file_bytes)

            stage = "uploaded"
            doc_id = await db.create_document(safe_filename)
            await self._update_status(doc_id=doc_id, status="uploaded")

            stage = "extracting"
            await self._update_status(doc_id=doc_id, status="extracting")
            file_meta = _FileMetadata(content_type=file.content_type, filename=safe_filename)
            file_text, page_boundaries = await extract_text_with_metadata(file_meta, file_bytes)
            file_text = clean_text(file_text)

            if not file_text:
                raise UploadPipelineError(
                    status_code=422,
                    code="no_text_extracted",
                    stage=stage,
                    message="No extractable text was found in the uploaded document.",
                )

            stage = "chunking"
            await self._update_status(doc_id=doc_id, status="chunking")
            langchain_docs = self._chunk_document_text(
                file_text,
                file_name=safe_filename,
                content_type=file.content_type,
            )

            if not langchain_docs:
                raise UploadPipelineError(
                    status_code=422,
                    code="no_chunks_generated",
                    stage=stage,
                    message="No chunks were generated from extracted text.",
                )

            stage = "embedding"
            await self._update_status(
                doc_id=doc_id,
                status="embedding",
                chunks={"total": len(langchain_docs), "processed": 0},
            )
            embeddings = await get_embeddings([doc.page_content for doc in langchain_docs])

            if len(embeddings) != len(langchain_docs):
                raise UploadPipelineError(
                    status_code=500,
                    code="embedding_mismatch",
                    stage=stage,
                    message="Embedding generation returned an unexpected number of vectors.",
                )

            stage = "storing"
            await self._update_status(doc_id=doc_id, status="storing")
            chunk_records = _build_chunk_records(langchain_docs, embeddings, page_boundaries)
            chunk_ids = await db.store_chunks_with_embeddings(doc_id, chunk_records)

            await self._update_status(
                doc_id=doc_id,
                status="completed",
                chunks={"total": len(langchain_docs), "processed": len(chunk_ids)},
            )

            logger.info(
                f"Successfully uploaded {len(chunk_ids)} chunks for document {doc_id}"
            )

            return {
                "message": "Uploaded",
                "document_id": doc_id,
                "chunks": len(chunk_ids),
                "status": "completed",
                "status_endpoint": f"/documents/{doc_id}/status",
            }

        except UploadPipelineError as e:
            if doc_id and not e.document_id:
                e.document_id = doc_id

            if doc_id:
                await self._handle_error(doc_id=doc_id, stage=e.stage, message=e.message)

            logger.warning(
                f"Upload validation/pipeline failed at stage={e.stage}: {e.message}"
            )
            raise

        except Exception as e:
            if doc_id:
                await self._handle_error(doc_id=doc_id, stage=stage, message=str(e))

            logger.error(f"Upload failed at stage={stage} for file {safe_filename}: {e}")
            raise UploadPipelineError(
                status_code=500,
                code="upload_failed",
                stage=stage,
                message="Upload failed. Please try again.",
                document_id=doc_id,
            )

    async def process_document_background(
        self,
        doc_id: str,
        file_name: str,
        content_type: str,
        file_bytes: bytes,
        rate_limiter=None,
    ) -> None:
        """
        Run the extraction→chunking→embedding→storing pipeline stages for a
        document that was already created and queued by the upload endpoint.

        Called exclusively by background workers; raises on unrecoverable error
        so the worker can apply retry / DLQ logic.
        """
        safe_filename = _sanitize_filename(file_name)
        file_meta = _FileMetadata(content_type=content_type, filename=safe_filename)
        stage = "extracting"

        try:
            await self._update_status(doc_id=doc_id, status="extracting")
            file_text, page_boundaries = await extract_text_with_metadata(file_meta, file_bytes)  # type: ignore[arg-type]
            file_text = clean_text(file_text)

            if not file_text:
                raise UploadPipelineError(
                    status_code=422,
                    code="no_text_extracted",
                    stage=stage,
                    message="No extractable text was found in the uploaded document.",
                    document_id=doc_id,
                )

            stage = "chunking"
            await self._update_status(doc_id=doc_id, status="chunking")
            langchain_docs = self._chunk_document_text(
                file_text,
                file_name=safe_filename,
                content_type=content_type,
            )

            if not langchain_docs:
                raise UploadPipelineError(
                    status_code=422,
                    code="no_chunks_generated",
                    stage=stage,
                    message="No chunks were generated from extracted text.",
                    document_id=doc_id,
                )

            stage = "embedding"
            await self._update_status(
                doc_id=doc_id,
                status="embedding",
                chunks={"total": len(langchain_docs), "processed": 0},
            )
            if rate_limiter is not None:
                await rate_limiter.acquire()
            embeddings = await get_embeddings([doc.page_content for doc in langchain_docs])

            if len(embeddings) != len(langchain_docs):
                raise UploadPipelineError(
                    status_code=500,
                    code="embedding_mismatch",
                    stage=stage,
                    message="Embedding generation returned an unexpected number of vectors.",
                    document_id=doc_id,
                )

            stage = "storing"
            await self._update_status(doc_id=doc_id, status="storing")
            chunk_records = _build_chunk_records(langchain_docs, embeddings, page_boundaries)
            chunk_ids = await db.store_chunks_with_embeddings(doc_id, chunk_records)

            await self._update_status(
                doc_id=doc_id,
                status="completed",
                chunks={"total": len(langchain_docs), "processed": len(chunk_ids)},
            )

            logger.info(
                f"Background processing complete: {len(chunk_ids)} chunks "
                f"stored for document {doc_id}"
            )

        except UploadPipelineError as e:
            await self._handle_error(doc_id=doc_id, stage=e.stage, message=e.message)
            logger.warning(
                f"Background pipeline failed at stage={e.stage} "
                f"for document {doc_id}: {e.message}"
            )
            raise

        except Exception as e:
            await self._handle_error(doc_id=doc_id, stage=stage, message=str(e))
            logger.error(
                f"Background pipeline unexpected error at stage={stage} "
                f"for document {doc_id}: {e}"
            )
            raise

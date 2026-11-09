import asyncio
import io
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from html.parser import HTMLParser

from fastapi import UploadFile
from pypdf import PdfReader

from services.docx_extraction import (
    DOCX_CONTENT_TYPE,
    DocxExtractionError,
    extract_docx_text,
    is_docx_content_type,
    is_docx_filename,
)
from services.text_cleaning_service import clean_docx_text, clean_text

logger = logging.getLogger(__name__)

# Accepted Markdown MIME types (normalized, no parameters).
MARKDOWN_CONTENT_TYPES = frozenset({"text/markdown", "text/x-markdown"})
MARKDOWN_FILENAME_SUFFIXES = (".md", ".markdown")

HTML_CONTENT_TYPES = frozenset({"text/html"})
HTML_FILENAME_SUFFIXES = (".html", ".htm")

_SKIP_HTML_TAG_CONTENT = frozenset({"script", "style", "noscript"})
_HTML_TABLE_CELL_TAGS = frozenset({"td", "th"})
# Separators survive ``clean_text``: single spaces stay; ``\n\n`` is a paragraph break.
_HTML_CELL_SEPARATOR = " "
_HTML_ROW_SEPARATOR = "\n\n"
_HTML_CHARSET_PATTERN = re.compile(
    rb"""<meta[^>]+charset\s*=\s*['"]?\s*([a-zA-Z0-9._-]+)""",
    re.IGNORECASE,
)
_HTML_HTTP_EQUIV_CHARSET_PATTERN = re.compile(
    rb"""<meta[^>]+http-equiv\s*=\s*['"]?content-type['"]?[^>]+"""
    rb"""content\s*=\s*['"][^'"]*charset\s*=\s*([a-zA-Z0-9._-]+)""",
    re.IGNORECASE,
)

# Inline/reference Markdown links become visible link text only; URLs are not fetched.
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]*\)")

# Separator between cleaned PDF pages in the assembled chunking string.
_PAGE_SEPARATOR = " "


def prepare_extracted_document_for_chunking(
    raw_text: str,
    page_boundaries: list["PageBoundary"],
    *,
    content_type: str | None = None,
) -> tuple[str, list["PageBoundary"]]:
    """
    Return cleaned document text and page boundaries in the same coordinate space.

    TXT inputs have no page boundaries and are cleaned as one string. PDF inputs
    are cleaned page-by-page, then joined so chunk offsets and page boundaries
    refer to the identical assembled normalized text. DOCX inputs preserve table
    cell and row delimiters from extraction while normalizing prose blocks.
    """
    if not page_boundaries:
        if is_docx_content_type(content_type):
            return clean_docx_text(raw_text), []
        return clean_text(raw_text), []

    cleaned_parts: list[str] = []
    new_boundaries: list[PageBoundary] = []
    cursor = 0

    for boundary in page_boundaries:
        page_raw = raw_text[boundary.start_offset : boundary.end_offset]
        page_clean = clean_text(page_raw)
        if not page_clean:
            continue

        if cleaned_parts:
            cursor += len(_PAGE_SEPARATOR)

        start = cursor
        cleaned_parts.append(page_clean)
        cursor += len(page_clean)
        new_boundaries.append(
            PageBoundary(
                page_number=boundary.page_number,
                start_offset=start,
                end_offset=cursor,
            )
        )

    return _PAGE_SEPARATOR.join(cleaned_parts), new_boundaries


@dataclass
class PageBoundary:
    """Character offset range for a single PDF page within the cleaned document text."""

    page_number: int
    start_offset: int
    end_offset: int


@dataclass
class ExtractedDocument:
    """Extractor output: raw text plus provenance, before cleaning and chunking."""

    text: str
    page_boundaries: list[PageBoundary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DocumentExtractionError(ValueError):
    """Raised when an extractor cannot produce text from the supplied bytes."""


class UnsupportedDocumentTypeError(DocumentExtractionError):
    """Raised when no extractor is registered for the requested content type."""


class DocumentExtractor(ABC):
    """
    Common interface for document extraction implementations.

    Implementations must be stateless so a single class can serve concurrent
    ingestion jobs; ``extract`` is synchronous and runs in a worker thread.
    """

    @abstractmethod
    def extract(self, contents: bytes, *, filename: str = "") -> ExtractedDocument:
        """Return the extracted text and provenance, or raise DocumentExtractionError."""


class PdfExtractor(DocumentExtractor):
    """PDF extraction via pypdf with per-page boundaries on the raw text."""

    def extract(self, contents: bytes, *, filename: str = "") -> ExtractedDocument:
        try:
            parts: list[str] = []
            page_boundaries: list[PageBoundary] = []
            cursor = 0
            reader = PdfReader(io.BytesIO(contents))

            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                page_text = text + "\n"
                start = cursor
                end = cursor + len(page_text)
                page_boundaries.append(
                    PageBoundary(page_number=page_num, start_offset=start, end_offset=end)
                )
                parts.append(page_text)
                cursor = end
                logger.debug(f"Extracted {len(text)} characters from page {page_num}")

            full_text = "".join(parts)
            logger.info(f"Total extracted text length: {len(full_text)}")
            return ExtractedDocument(text=full_text, page_boundaries=page_boundaries)
        except Exception as e:
            logger.error(f"Failed to parse PDF file {filename}: {e}")
            raise DocumentExtractionError("Failed to parse PDF content.") from e


class _HTMLTextExtractor(HTMLParser):
    """Collect visible text from HTML fragments; script/style bodies are omitted."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _SKIP_HTML_TAG_CONTENT:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in _SKIP_HTML_TAG_CONTENT and self._skip_depth:
            self._skip_depth -= 1
        elif self._skip_depth == 0:
            if tag_lower in _HTML_TABLE_CELL_TAGS:
                self._parts.append(_HTML_CELL_SEPARATOR)
            elif tag_lower == "tr":
                self._parts.append(_HTML_ROW_SEPARATOR)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _extract_visible_html_text(html: str, *, strict_failure: bool = False) -> str:
    """
    Reduce HTML to visible text without executing scripts or fetching resources.

    ``script``/``style``/``noscript`` bodies are omitted. When ``strict_failure``
    is true, a parse failure that yields no visible text raises DocumentExtractionError.
    """
    if "<" not in html:
        return html
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
        parser.close()
        return parser.get_text()
    except Exception as exc:
        fallback = re.sub(r"<[^>]+>", "", html)
        if strict_failure and html.strip() and not fallback.strip():
            raise DocumentExtractionError("Failed to parse HTML content.") from exc
        return fallback


def _strip_embedded_html(text: str) -> str:
    """Remove HTML markup from Markdown payloads without executing scripts."""
    return _extract_visible_html_text(text)


def _html_declared_charset(contents: bytes) -> str | None:
    """Return a charset name from early ``<meta>`` tags when present."""
    head = contents[:8192]
    for pattern in (_HTML_CHARSET_PATTERN, _HTML_HTTP_EQUIV_CHARSET_PATTERN):
        match = pattern.search(head)
        if match:
            try:
                return match.group(1).decode("ascii").strip().lower()
            except UnicodeDecodeError:
                continue
    return None


def _decode_html_contents(contents: bytes, *, filename: str = "") -> str:
    """Decode HTML bytes using declared charset, then utf-8, then cp1254."""
    encodings: list[str] = []
    declared = _html_declared_charset(contents)
    if declared:
        encodings.append(declared)
    encodings.extend(["utf-8", "cp1254"])

    seen: set[str] = set()
    for encoding in encodings:
        normalized = encoding.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        try:
            return contents.decode(normalized)
        except (UnicodeDecodeError, LookupError):
            continue

    logger.error(f"Failed to decode HTML file {filename}: no supported encoding matched")
    raise DocumentExtractionError("Failed to decode HTML content.")


def _normalize_markdown_links(text: str) -> str:
    return _MARKDOWN_LINK_PATTERN.sub(r"\1", text)


def is_markdown_content_type(content_type: str | None) -> bool:
    return _normalize_content_type(content_type) in MARKDOWN_CONTENT_TYPES


def is_markdown_filename(filename: str) -> bool:
    lower = (filename or "").lower()
    return any(lower.endswith(suffix) for suffix in MARKDOWN_FILENAME_SUFFIXES)


def is_html_content_type(content_type: str | None) -> bool:
    return _normalize_content_type(content_type) in HTML_CONTENT_TYPES


def is_html_filename(filename: str) -> bool:
    lower = (filename or "").lower()
    return any(lower.endswith(suffix) for suffix in HTML_FILENAME_SUFFIXES)


class HtmlExtractor(DocumentExtractor):
    """
    HTML extraction to visible text only (no script execution, no network I/O).

    Remote resources referenced by tags are not fetched. ``page_number`` provenance
    is not populated for HTML inputs.
    """

    def extract(self, contents: bytes, *, filename: str = "") -> ExtractedDocument:
        file_text = _decode_html_contents(contents, filename=filename)

        if "\x00" in file_text:
            logger.error(f"HTML file {filename} contains null bytes")
            raise DocumentExtractionError("Failed to parse HTML content.")

        file_text = _extract_visible_html_text(file_text, strict_failure=True)
        logger.info(f"Extracted {len(file_text)} characters from HTML file")
        return ExtractedDocument(text=file_text)


class MarkdownExtractor(DocumentExtractor):
    """
    Markdown extraction preserving headings, lists, and code fences as text.

    Embedded HTML is reduced to visible text (no script execution). Link targets
    are not fetched; ``[label](url)`` becomes ``label`` in extracted text.
    """

    def extract(self, contents: bytes, *, filename: str = "") -> ExtractedDocument:
        try:
            file_text = contents.decode("utf-8")
        except UnicodeDecodeError:
            try:
                file_text = contents.decode("cp1254")
            except UnicodeDecodeError as e:
                logger.error(f"Failed to decode Markdown file {filename}: {e}")
                raise DocumentExtractionError("Failed to decode Markdown content.") from e

        if "\x00" in file_text:
            logger.error(f"Markdown file {filename} contains null bytes")
            raise DocumentExtractionError("Failed to parse Markdown content.")

        file_text = _normalize_markdown_links(_strip_embedded_html(file_text))
        logger.info(f"Extracted {len(file_text)} characters from Markdown file")
        return ExtractedDocument(text=file_text)


class DocxExtractor(DocumentExtractor):
    """
    DOCX extraction via safe ZIP/XML parsing only (no macros, no OCR, no network).

    Embedded media without text is omitted. ``page_number`` provenance is not populated.
    """

    def extract(self, contents: bytes, *, filename: str = "") -> ExtractedDocument:
        try:
            text = extract_docx_text(contents, filename=filename)
        except DocxExtractionError as exc:
            message = str(exc)
            if message.startswith("Encrypted"):
                raise DocumentExtractionError(message) from exc
            raise DocumentExtractionError("Failed to parse DOCX content.") from exc
        logger.info(f"Extracted {len(text)} characters from DOCX file")
        return ExtractedDocument(text=text)


class PlainTextExtractor(DocumentExtractor):
    """Plain-text extraction (utf-8, cp1254 fallback) with no page boundaries."""

    def extract(self, contents: bytes, *, filename: str = "") -> ExtractedDocument:
        try:
            file_text = contents.decode("utf-8")
        except UnicodeDecodeError:
            try:
                file_text = contents.decode("cp1254")  # Turkish Windows fallback
            except UnicodeDecodeError as e:
                logger.error(f"Failed to decode text file {filename}: {e}")
                raise DocumentExtractionError("Failed to decode text content.") from e
        logger.info(f"Extracted {len(file_text)} characters from TXT file")
        return ExtractedDocument(text=file_text)


# Registry keyed by normalized MIME type. Registering a new extractor class here
# (or via register_document_extractor) is the only change a new format needs.
_EXTRACTOR_REGISTRY: dict[str, type[DocumentExtractor]] = {
    "application/pdf": PdfExtractor,
    "text/plain": PlainTextExtractor,
    "text/html": HtmlExtractor,
    "text/markdown": MarkdownExtractor,
    "text/x-markdown": MarkdownExtractor,
    DOCX_CONTENT_TYPE: DocxExtractor,
}


def _normalize_content_type(content_type: str | None) -> str:
    """Lowercase a MIME type and drop parameters such as ``; charset=utf-8``."""
    return (content_type or "").split(";", 1)[0].strip().lower()


def register_document_extractor(
    content_type: str,
    extractor_cls: type[DocumentExtractor],
) -> None:
    """Map a MIME type to an extractor class, replacing any existing mapping."""
    _EXTRACTOR_REGISTRY[_normalize_content_type(content_type)] = extractor_cls


def build_document_extractor(
    content_type: str | None,
    filename: str = "",
) -> DocumentExtractor:
    """Resolve a content type to a fresh extractor instance."""
    extractor_cls = _EXTRACTOR_REGISTRY.get(_normalize_content_type(content_type))
    if extractor_cls is None:
        logger.error(f"Unsupported file type: {content_type} ({filename})")
        raise UnsupportedDocumentTypeError(f"Unsupported file type: {content_type}")
    return extractor_cls()


def _extract_text_with_metadata_sync(
    content_type: str | None,
    filename: str,
    contents: bytes,
) -> tuple[str, list[PageBoundary]]:
    """
    Synchronous extraction body: select an extractor and run it.

    Raises DocumentExtractionError (a ValueError) for unsupported file types or
    unreadable payloads.
    """
    extractor = build_document_extractor(content_type, filename=filename)
    document = extractor.extract(contents, filename=filename)
    for warning in document.warnings:
        logger.warning(f"Extraction warning for {filename}: {warning}")
    return document.text, document.page_boundaries


async def extract_text_from_file(file: UploadFile, contents: bytes | None = None) -> str:
    """
    Extract text from a PDF, TXT, Markdown, HTML, or DOCX UploadFile.
    Raises ValueError for unsupported file types or unreadable payloads.
    """
    text, _ = await extract_text_with_metadata(file, contents)
    return text


async def extract_text_with_metadata(
    file: UploadFile,
    contents: bytes | None = None,
) -> tuple[str, list[PageBoundary]]:
    """
    Extract text and per-page boundary information from an allowlisted UploadFile.

    Returns:
        (full_text, page_boundaries) where page_boundaries is populated for PDFs
        and empty for other text-like formats.
    Raises ValueError for unsupported file types or unreadable payloads.
    """
    if contents is None:
        contents = await file.read()

    return await asyncio.to_thread(
        _extract_text_with_metadata_sync,
        file.content_type,
        file.filename or "",
        contents,
    )

import io
import logging
from dataclasses import dataclass

from fastapi import UploadFile
from pypdf import PdfReader

logger = logging.getLogger(__name__)


@dataclass
class PageBoundary:
    """Character offset range for a single PDF page within the full extracted text."""

    page_number: int
    start_offset: int
    end_offset: int


async def extract_text_from_file(file: UploadFile, contents: bytes | None = None) -> str:
    """
    Extract text from a PDF or TXT UploadFile.
    Raises ValueError for unsupported file types or unreadable payloads.
    """
    text, _ = await extract_text_with_metadata(file, contents)
    return text


async def extract_text_with_metadata(
    file: UploadFile,
    contents: bytes | None = None,
) -> tuple[str, list[PageBoundary]]:
    """
    Extract text and per-page boundary information from a PDF or TXT UploadFile.

    Returns:
        (full_text, page_boundaries) where page_boundaries is populated for PDFs
        and empty for plain-text files.
    Raises ValueError for unsupported file types or unreadable payloads.
    """
    if contents is None:
        contents = await file.read()

    if file.content_type == "application/pdf":
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
                page_boundaries.append(PageBoundary(page_number=page_num, start_offset=start, end_offset=end))
                parts.append(page_text)
                cursor = end
                logger.debug(f"Extracted {len(text)} characters from page {page_num}")

            full_text = "".join(parts)
            logger.info(f"Total extracted text length: {len(full_text)}")
            return full_text, page_boundaries
        except Exception as e:
            logger.error(f"Failed to parse PDF file {file.filename}: {e}")
            raise ValueError("Failed to parse PDF content.")

    if file.content_type == "text/plain":
        try:
            file_text = contents.decode("utf-8")
        except UnicodeDecodeError:
            file_text = contents.decode("cp1254")  # Turkish Windows fallback
        logger.info(f"Extracted {len(file_text)} characters from TXT file")
        return file_text, []

    logger.error(f"Unsupported file type: {file.content_type}")
    raise ValueError(f"Unsupported file type: {file.content_type}")

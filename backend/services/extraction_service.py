import io
import logging

from fastapi import UploadFile
from pypdf import PdfReader

logger = logging.getLogger(__name__)


async def extract_text_from_file(file: UploadFile, contents: bytes | None = None) -> str:
    """
    Extract text from a PDF or TXT UploadFile.
    Raises ValueError for unsupported file types or unreadable payloads.
    """
    if contents is None:
        contents = await file.read()

    if file.content_type == "application/pdf":
        try:
            file_text = ""
            reader = PdfReader(io.BytesIO(contents))
            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                file_text += text + "\n"
                logger.debug(f"Extracted {len(text)} characters from page {page_num}")
            logger.info(f"Total extracted text length: {len(file_text)}")
            return file_text
        except Exception as e:
            logger.error(f"Failed to parse PDF file {file.filename}: {e}")
            raise ValueError("Failed to parse PDF content.")

    if file.content_type == "text/plain":
        try:
            file_text = contents.decode("utf-8")
        except UnicodeDecodeError:
            file_text = contents.decode("cp1254")  # Turkish Windows fallback
        logger.info(f"Extracted {len(file_text)} characters from TXT file")
        return file_text

    logger.error(f"Unsupported file type: {file.content_type}")
    raise ValueError(f"Unsupported file type: {file.content_type}")

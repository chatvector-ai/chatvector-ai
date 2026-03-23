"""
Text cleaning and normalization for extracted document content.
Applied between extraction and chunking to improve embedding quality
and downstream RAG retrieval accuracy.

Strategy: "nuclear" flattening — all line breaks are converted to spaces,
producing a single clean prose string suitable for chunking and embedding.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    if not text:
        return text

    original_len = len(text)

    # 1. Unicode normalization (ligatures, fullwidth chars, NBSP → space, etc.)
    text = unicodedata.normalize("NFKC", text)
    # 2. Remove non-printable control chars; keep \t (0x09), \n (0x0A), \r (0x0D)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    # 3. Remove bullet point characters
    text = re.sub(r"[●•▪▸▹◦‣⁃◆◇■□▶▷]", "", text)
    # 4. Remove soft hyphens; rejoin hyphenated line breaks (PDF word-wrap artifact)
    text = text.replace("\u00ad", "")
    text = re.sub(r"-\n(\S)", r"\1", text)
    # 5. Flatten all remaining line breaks to spaces
    text = text.replace("\n", " ").replace("\r", " ")
    # 6. Normalize all whitespace runs (spaces and tabs) to a single space
    text = re.sub(r"[ \t]+", " ", text)

    text = text.strip()

    logger.debug("Text cleaning: %d → %d characters", original_len, len(text))
    return text

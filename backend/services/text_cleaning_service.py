"""
Text cleaning and normalization for extracted document content.
Applied between extraction and chunking to improve embedding quality
and downstream RAG retrieval accuracy.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
   
    if not text:
        return text

    original_len = len(text)

    # 1. Unicode normalization
    text = unicodedata.normalize("NFKC", text)
    # 2. Remove non-printable control chars; keep \t (0x09), \n (0x0A), \r (0x0D)
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    # 3. Remove soft hyphens
    text = text.replace("\u00ad", "")
    # 4. Rejoin hyphenated line breaks (PDF word-wrap artifact)
    #    "connec-\ntion" → "connection"
    text = re.sub(r"-\n(\S)", r"\1", text)
    # 5. Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 6. Strip trailing whitespace per line
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    # 7. Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 8. Collapse multiple inline spaces/tabs to a single space
    text = re.sub(r"[ \t]{2,}", " ", text)
    # 9. Final strip
    text = text.strip()

    logger.debug("Text cleaning: %d → %d characters", original_len, len(text))
    return text

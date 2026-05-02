import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "32000"))


@dataclass
class SessionContext:
    recent_queries: list[str] = field(default_factory=list)
    active_documents: list[str] = field(default_factory=list)


def build_context_from_chunks(
    chunks: list, session_context: Optional[SessionContext] = None
) -> str:
    """
    Combine chunk texts into a single context string for the LLM.

    Each chunk is prefixed with a source label so the model can cite
    the originating file and page in its answer.

    Chunks are dropped (whole, from the end) if the total would exceed
    MAX_CONTEXT_CHARS, preserving formatting of all included chunks.
    """
    parts: list[str] = []
    total_chars = 0
    separator = "\n\n"
    sep_len = len(separator)

    # 1. Inject Session Context (if provided)
    if session_context:
        # TODO(Phase 3B): Future integration point for semantic memory retrieval.
        session_lines = ["[Session History]"]
        if session_context.recent_queries:
            session_lines.append("Recent queries: " + ", ".join(session_context.recent_queries))
        if session_context.active_documents:
            session_lines.append("Active documents: " + ", ".join(session_context.active_documents))
        
        if len(session_lines) > 1:
            session_lines.append("\n[Retrieved Context]")
            session_part = "\n".join(session_lines)
            parts.append(session_part)
            total_chars += len(session_part)

    for i, chunk in enumerate(chunks):
        label = f"[Source: {chunk.file_name or 'unknown'}"
        if chunk.page_number is not None:
            label += f", page {chunk.page_number}"
        label += "]"
        part = f"{label}\n{chunk.chunk_text or ''}"

        addition = (sep_len + len(part)) if parts else len(part)
        if total_chars + addition > MAX_CONTEXT_CHARS:
            if not parts:
                # Single chunk exceeds cap; include it rather than returning empty context.
                parts.append(part)
                dropped = len(chunks) - i - 1
                used = len(part)
            else:
                dropped = len(chunks) - i
                used = total_chars
            logger.warning(
                "Context truncated: dropped %d of %d chunks to stay within "
                "MAX_CONTEXT_CHARS=%d (used %d chars)",
                dropped,
                len(chunks),
                MAX_CONTEXT_CHARS,
                used,
            )
            break

        parts.append(part)
        total_chars += addition

    context = separator.join(parts)
    logger.info("Constructed context of length %d", len(context))
    return context

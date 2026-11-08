import logging
import os
from dataclasses import dataclass
from typing import Optional
from core.session import SessionContext

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS: int = int(os.getenv("MAX_CONTEXT_CHARS", "32000"))


def _source_page_label(page_number: int | None, page_end: int | None) -> str:
    if page_number is None:
        return ""
    if page_end is None or page_end == page_number:
        return f", page {page_number}"
    return f", pages {page_number}-{page_end}"


@dataclass(frozen=True)
class PackedContext:
    """Context string and the chunks that were written into it.

    ``text`` is the string the model sees. ``included_chunks`` is the
    structured inclusion list, in packer order. Callers match those chunk
    objects by document id and chunk index. They do not scan ``text``.
    """

    text: str
    included_chunks: tuple[object, ...]


def build_context_from_chunks(
    chunks: list,
    session_context: Optional[SessionContext] = None,
    *,
    max_chars: int | None = None,
) -> PackedContext:
    """
    Combine chunk texts into a single context string for the LLM.

    Each chunk is prefixed with a source label so the model can cite
    the originating file and page in its answer.

    Chunks are dropped (whole, from the end) if the total would exceed
    MAX_CONTEXT_CHARS, preserving formatting of all included chunks.
    ``max_chars`` overrides that process cap for one assembly call.

    The returned string matches the previous assembly. The inclusion list
    records which input chunks were written; session history is not a chunk.
    """
    limit = MAX_CONTEXT_CHARS if max_chars is None else max_chars
    parts: list[str] = []
    included: list = []
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
        
        if session_context.chat_history:
            for msg in session_context.chat_history:
                role_label = "User" if msg.get("role") == "user" else "Assistant"
                session_lines.append(f"[{role_label}]: {msg.get('content')}")
        
        if len(session_lines) > 1:
            session_lines.append("\n[Retrieved Context]")
            session_part = "\n".join(session_lines)
            parts.append(session_part)
            total_chars += len(session_part)

    for i, chunk in enumerate(chunks):
        label = f"[Source: {chunk.file_name or 'unknown'}"
        label += _source_page_label(
            chunk.page_number,
            getattr(chunk, "page_end", None),
        )
        label += "]"
        part = f"{label}\n{chunk.chunk_text or ''}"

        addition = (sep_len + len(part)) if parts else len(part)
        if total_chars + addition > limit:
            if not parts:
                # Single chunk exceeds cap; include it rather than returning empty context.
                parts.append(part)
                included.append(chunk)
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
                limit,
                used,
            )
            break

        parts.append(part)
        included.append(chunk)
        total_chars += addition

    context = separator.join(parts)
    logger.info("Constructed context of length %d", len(context))
    return PackedContext(text=context, included_chunks=tuple(included))

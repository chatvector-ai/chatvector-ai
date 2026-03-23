import logging

logger = logging.getLogger(__name__)


def build_context_from_chunks(chunks: list) -> str:
    """
    Combine chunk texts into a single context string for the LLM.

    Each chunk is prefixed with a source label so the model can cite
    the originating file and page in its answer.
    """
    parts: list[str] = []
    for chunk in chunks:
        label = f"[Source: {chunk.file_name or 'unknown'}"
        if chunk.page_number is not None:
            label += f", page {chunk.page_number}"
        label += "]"
        parts.append(f"{label}\n{chunk.chunk_text or ''}")
    context = "\n\n".join(parts)
    logger.info(f"Constructed context of length {len(context)}")
    return context

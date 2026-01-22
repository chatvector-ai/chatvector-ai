import logging

logger = logging.getLogger(__name__)

def build_context_from_chunks(chunks: list[dict]) -> str:
    """
    Combine chunk texts into a single string context for the LLM.
    """
    context = "\n".join([c.get("chunk_text", "") for c in chunks])
    logger.info(f"Constructed context of length {len(context)}")
    return context
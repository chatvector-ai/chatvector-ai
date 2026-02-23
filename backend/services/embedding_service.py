import asyncio
import logging
from google import genai
from core.config import config
from utils.retry import retry_async

logger = logging.getLogger(__name__)
client = genai.Client(api_key=config.GEN_AI_KEY)
EMBEDDING_DIM = 3072
MODEL_NAME = "models/gemini-embedding-001"


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts.
    Always returns list[list[float]] with fixed dimension.
    """
    async def _get_embeddings_operation() -> list[list[float]]:
        """Internal operation to perform the actual embedding generation."""
        logger.info(f"Requesting embeddings for {len(texts)} inputs")
        result = await asyncio.to_thread(
            client.models.embed_content,
            model=MODEL_NAME,
            contents=texts,
        )
        embeddings = [e.values for e in result.embeddings]
        return embeddings

    try:
        return await retry_async(
            _get_embeddings_operation,
            max_retries=3,
            base_delay=1.0,
            backoff=2.0,
            func_name="get_embeddings"
        )
    except Exception as e:
        logger.error(f"Embedding batch failed after retries; returning zero vectors ({EMBEDDING_DIM} dims): {e}")
        return [[0.0] * EMBEDDING_DIM for _ in texts]


async def get_embedding(text: str) -> list[float]:
    """
    Convenience wrapper for single-text embedding.
    """
    return (await get_embeddings([text]))[0]
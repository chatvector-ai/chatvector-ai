import asyncio
import logging
from google import genai
from core.config import config
from utils.retry import retry_async

logger = logging.getLogger(__name__)
client = genai.Client(api_key=config.GEN_AI_KEY)
EMBEDDING_DIM = 3072
MODEL_NAME = "models/gemini-embedding-001"
BATCH_SIZE = 100


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts.
    Always returns list[list[float]] with fixed dimension.

    Splits inputs into sequential batches of at most BATCH_SIZE to stay
    within the Gemini API limit. Raises on failure so callers can apply
    retry/rollback logic — no silent zero-vector fallback.
    """
    all_embeddings: list[list[float]] = []

    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch = texts[batch_start : batch_start + BATCH_SIZE]

        async def _embed_batch(_batch: list[str] = batch) -> list[list[float]]:
            logger.info(f"Requesting embeddings for {len(_batch)} inputs")
            result = await asyncio.to_thread(
                client.models.embed_content,
                model=MODEL_NAME,
                contents=_batch,
            )
            return [e.values for e in result.embeddings]

        batch_embeddings = await retry_async(
            _embed_batch,
            max_retries=3,
            base_delay=1.0,
            backoff=2.0,
            timeout=30.0,
            func_name="embedding_service.get_embeddings",
        )
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


async def get_embedding(text: str) -> list[float]:
    """
    Convenience wrapper for single-text embedding.
    """
    return (await get_embeddings([text]))[0]
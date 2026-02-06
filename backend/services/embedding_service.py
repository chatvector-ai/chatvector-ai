import asyncio
import logging
from google import genai
from core.config import config

logger = logging.getLogger(__name__)

client = genai.Client(api_key=config.GEN_AI_KEY)

EMBEDDING_DIM = 3072
MODEL_NAME = "models/gemini-embedding-001"


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts.
    Always returns List[List[float]] with fixed dimension.
    """
    for attempt in range(3):
        try:
            logger.info(
                f"Requesting embeddings for {len(texts)} inputs "
                f"(Attempt {attempt + 1}/3)"
            )

            result = await asyncio.to_thread(
                client.models.embed_content,
                model=MODEL_NAME,
                contents=texts,
            )

            embeddings = [e.values for e in result.embeddings]

            # Safety check
            for i, emb in enumerate(embeddings):
                if len(emb) != EMBEDDING_DIM:
                    raise ValueError(
                        f"Embedding {i} has {len(emb)} dims, expected {EMBEDDING_DIM}"
                    )

            return embeddings

        except Exception as e:
            wait_time = (attempt + 1) * 2
            logger.warning(
                f"Embedding batch attempt {attempt + 1} failed, retrying: {e}"
            )
            await asyncio.sleep(wait_time)

    logger.error(
        f"Embedding batch failed after retries; returning zero vectors ({EMBEDDING_DIM} dims)"
    )
    return [[0.0] * EMBEDDING_DIM for _ in texts]


async def get_embedding(text: str) -> list[float]:
    """
    Convenience wrapper for single-text embedding.
    """
    return (await get_embeddings([text]))[0]
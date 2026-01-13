import asyncio
import google.generativeai as genai
from backend.core.config import config
import logging

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEN_AI_KEY)

async def get_embedding(text: str):
    for attempt in range(3):
        logger.debug(f"Attempt {attempt + 1} to get embedding for text.")
        try:
            logger.info("Requesting embedding from GenAI.")
            result = genai.embed_content(
                model="models/embedding-001", 
                content=text
            )
            return result["embedding"]
        except Exception:
            wait_time = (attempt + 1) * 2
            logger.warning(f"Embedding generation failed (Attempt {attempt + 1}/3). Error: {wait_time}. Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)
    logger.error("Failed to get embedding after 3 attempts. Returning zero vector.")
    return [0.0] * 768

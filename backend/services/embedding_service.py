import asyncio
import google.generativeai as genai
from backend.core.config import config

genai.configure(api_key=config.GEN_AI_KEY)


async def get_embedding(text: str):
    for attempt in range(3):
        try:
            result = genai.embed_content(
                model="models/embedding-001",
                content=text
            )
            return result["embedding"]
        except Exception:
            await asyncio.sleep((attempt + 1) * 2)

    return [0.0] * 768

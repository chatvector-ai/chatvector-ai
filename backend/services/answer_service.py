"""LLM answer generation for RAG chat using the Gemini API (same client stack as embeddings)."""

import asyncio
from google import genai
from core.config import config
import logging

logger = logging.getLogger(__name__)

# Use the SAME client as embedding service
client = genai.Client(api_key=config.GEN_AI_KEY)

async def generate_answer(question: str, context: str) -> str:
    """
    Generate an answer using Gemini LLM based on the provided context.
    """
    prompt = f"""
    Answer the question based ONLY on the context.

    CONTEXT:
    {context}

    QUESTION:
    {question}

    If you cannot answer, say "Not enough information."
    """

    try:
        # Use the new API like embeddings do
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",  
            contents=prompt
        )
        
        answer = response.text or "No response."
        logger.info(f"Answer generated successfully")
        return answer
        
    except Exception as e:
        logger.error(f"Failed to generate answer: {e}")
        return "Error generating answer."
import asyncio
from functools import partial
import logging
from google.generativeai import GenerativeModel

logger = logging.getLogger(__name__)

async def generate_answer(question: str, context: str) -> str:
    """
    Generate an answer using Gemini LLM based on the provided context.

    Runs synchronously blocking code in a thread executor to avoid blocking
    the FastAPI event loop.
    """
    prompt = f"""
    Answer the question based ONLY on the context.

    CONTEXT:
    {context}

    QUESTION:
    {question}

    If you cannot answer, say "Not enough information."
    """

    model = GenerativeModel("gemini-2.0-flash")

    try:
        loop = asyncio.get_running_loop()
        func = partial(model.generate_content, prompt)
        result = await loop.run_in_executor(None, func)
        answer = result.text or "No response."
        logger.info(f"Answer generated successfully for question of length {len(question)}")
        return answer
    except Exception as e:
        logger.error(f"Failed to generate answer: {e}")
        return "Error generating answer."

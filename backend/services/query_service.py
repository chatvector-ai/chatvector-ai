"""Query transformation for retrieval (rewrite, expand, step-back)."""

import asyncio
import logging

from google.genai import types

from core.config import config

logger = logging.getLogger(__name__)

_TRANSFORM_TEMPERATURE = 0.1
_TRANSFORM_MAX_OUTPUT_TOKENS = 512


async def _llm_transform(system_instruction: str, user_text: str) -> str | None:
    from services.answer_service import client as _genai_client

    config_obj = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=_TRANSFORM_TEMPERATURE,
        max_output_tokens=_TRANSFORM_MAX_OUTPUT_TOKENS,
    )
    try:
        response = await asyncio.to_thread(
            _genai_client.models.generate_content,
            model="gemini-2.5-flash",
            contents=user_text,
            config=config_obj,
        )
        text = (response.text or "").strip()
        return text if text else None
    except Exception as e:
        logger.warning(
            "Query transformation LLM call failed (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
        )
        return None


async def rewrite_query(question: str) -> str:
    system_instruction = (
        "You are a query rewriting assistant. Rephrase the following question to be "
        "more specific and retrieval-friendly for semantic search over documents. "
        "Return only the rewritten query, nothing else."
    )
    rewritten = await _llm_transform(system_instruction, question)
    if rewritten is None:
        return question
    return rewritten


async def expand_query(question: str) -> list[str]:
    system_instruction = (
        "You are a query expansion assistant. Generate exactly 2 alternative phrasings "
        "of the following question for semantic search. Return only the alternatives, "
        "one per line, no numbering, no explanation."
    )
    raw = await _llm_transform(system_instruction, question)
    if raw is None:
        return [question]
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    alternatives = lines[:2]
    if not alternatives:
        return [question]
    return [question, *alternatives]


async def stepback_query(question: str) -> list[str]:
    system_instruction = (
        "You are a step-back prompting assistant. Given a specific question, identify "
        "the broader concept or principle it relates to. Return only the broader question, "
        "nothing else."
    )
    broader = await _llm_transform(system_instruction, question)
    if broader is None:
        return [question]
    return [question, broader]


async def transform_query(question: str) -> list[str]:
    if not config.QUERY_TRANSFORMATION_ENABLED:
        return [question]

    strategy = config.QUERY_TRANSFORMATION_STRATEGY
    if strategy == "rewrite":
        return [await rewrite_query(question)]
    if strategy == "expand":
        return await expand_query(question)
    if strategy == "stepback":
        return await stepback_query(question)

    logger.warning(
        "Unknown QUERY_TRANSFORMATION_STRATEGY=%r; returning original question unchanged",
        strategy,
    )
    return [question]

"""LLM answer generation for RAG chat using the Gemini API (same client stack as embeddings)."""

import asyncio
import logging
from pathlib import Path

import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError

from core.config import config

logger = logging.getLogger(__name__)

# Use the SAME client as embedding service
client = genai.Client(api_key=config.GEN_AI_KEY)


def _load_system_prompt() -> str:
    path = Path(config.SYSTEM_PROMPT_PATH)
    if not path.is_file():
        raise FileNotFoundError(
            f"System prompt file not found at {path} (SYSTEM_PROMPT_PATH is set but the file is missing)."
        )
    return path.read_text(encoding="utf-8").strip()


_SYSTEM_PROMPT = _load_system_prompt()


def _msg_missing_api_key() -> str:
    return "LLM service is not available: API key is missing or not configured."


def _msg_invalid_api_key() -> str:
    return "LLM request failed: invalid or unauthorized API key."


def _msg_rate_limit() -> str:
    return "LLM request failed: rate limit or quota exceeded. Please try again later."


def _msg_timeout_or_connection() -> str:
    return "LLM request failed: the service timed out or could not be reached."


def _msg_unexpected() -> str:
    return "LLM request failed due to an unexpected error."


async def generate_answer(question: str, context: str) -> str:
    """
    Generate an answer using Gemini LLM based on the provided context.
    """
    contents = f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"

    key = config.GEN_AI_KEY
    if key is None or not str(key).strip():
        logger.error(
            "LLM cannot run: GEN_AI_KEY is missing or empty",
            extra={"error_type": "MissingAPIKey"},
        )
        return _msg_missing_api_key()

    config_obj = types.GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        temperature=config.LLM_TEMPERATURE,
        max_output_tokens=config.LLM_MAX_OUTPUT_TOKENS,
    )

    try:
        # Use the new API like embeddings do
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=contents,
            config=config_obj,
        )

        answer = response.text or "No response."
        logger.info("Answer generated successfully")
        return answer

    except APIError as e:
        code = getattr(e, "code", None)
        status = str(getattr(e, "status", "") or "").lower()
        msg = str(e).lower()
        exc_name = type(e).__name__
        if code == 429 or "resource_exhausted" in status or "quota" in msg:
            logger.error(
                "LLM rate limit or quota (%s): %s",
                exc_name,
                e,
                extra={"error_type": exc_name, "http_code": code},
            )
            return _msg_rate_limit()
        if code in (401, 403) or "unauthenticated" in msg or "permission_denied" in status:
            logger.error(
                "LLM API key rejected or unauthorized (%s): %s",
                exc_name,
                e,
                extra={"error_type": exc_name, "http_code": code},
            )
            return _msg_invalid_api_key()
        if code == 400 and ("api key" in msg or "api_key" in msg or "invalid key" in msg):
            logger.error(
                "LLM invalid API key (%s): %s",
                exc_name,
                e,
                extra={"error_type": exc_name, "http_code": code},
            )
            return _msg_invalid_api_key()
        logger.error(
            "LLM API error (%s): %s",
            exc_name,
            e,
            exc_info=True,
            extra={"error_type": exc_name, "http_code": code},
        )
        return _msg_unexpected()

    except httpx.TimeoutException as e:
        logger.error(
            "LLM request timeout (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        return _msg_timeout_or_connection()

    except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.NetworkError) as e:
        logger.error(
            "LLM connection error (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        return _msg_timeout_or_connection()

    except (TimeoutError, ConnectionError, BrokenPipeError) as e:
        logger.error(
            "LLM timeout or connection error (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        return _msg_timeout_or_connection()

    except Exception as e:
        logger.error(
            "LLM unexpected error (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        return _msg_unexpected()

"""Query transformation for retrieval (rewrite, expand, step-back)."""

import logging
from dataclasses import dataclass

from core.config import config
from services.providers import get_llm_provider

logger = logging.getLogger(__name__)

_TRANSFORM_TEMPERATURE = 0.1


@dataclass(frozen=True)
class QueryTransformResult:
    """Query transformation output for retrieval and optional debug traces."""

    queries: list[str]
    original_query: str
    history_resolved_query: str | None = None
    transformation_strategy: str | None = None

    def to_retrieval_debug(self) -> dict:
        """Build opt-in retrieval_debug payload for chat/batch responses."""
        payload: dict = {
            "original_query": self.original_query,
            "transformed_queries": self.queries,
        }
        if (
            self.history_resolved_query is not None
            and self.history_resolved_query != self.original_query
        ):
            payload["history_resolved_query"] = self.history_resolved_query
        if self.transformation_strategy is not None:
            payload["transformation_strategy"] = self.transformation_strategy
        return payload
_TRANSFORM_MAX_OUTPUT_TOKENS = 512


async def _llm_transform(system_instruction: str, user_text: str) -> str | None:
    try:
        provider = get_llm_provider()
        text = await provider.generate(
            user_text,
            system_instruction=system_instruction,
            temperature=_TRANSFORM_TEMPERATURE,
            max_output_tokens=_TRANSFORM_MAX_OUTPUT_TOKENS,
        )
        text = (text or "").strip()
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


def _format_history_context(history: list[dict]) -> str:
    """Render session history as a conversational context string.

    History arrives ordered most-recent-first (as returned by get_session_history).
    We reverse it so the prompt reads chronologically.
    """
    lines: list[str] = []
    for msg in reversed(history):
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
    return "\n".join(lines)


async def _resolve_to_standalone(question: str, history: list[dict]) -> str:
    """Rewrite a follow-up question into a self-contained standalone query.

    Uses the provided conversation history to resolve pronouns ("it", "they",
    "that"), implicit references ("the second option", "the earlier plan"), and
    omitted subjects so that the resulting question can be used for retrieval
    without any surrounding context.

    Latency/cost note: this makes one additional LLM call on top of whatever
    transformation strategy follows.  Keep the history window small
    (QUERY_TRANSFORMATION_HISTORY_WINDOW, default 6 messages) to limit token
    overhead.  The call is skipped entirely when no history is provided.
    """
    history_text = _format_history_context(history)
    system_instruction = (
        "You are a query resolution assistant. Given a conversation history and a "
        "follow-up question, rewrite the follow-up as a complete standalone question "
        'that does not rely on context from the conversation. Resolve pronouns ("it", '
        '"they", "that"), references ("the second option", "the earlier plan"), and '
        "omitted subjects. If the question is already standalone, return it unchanged. "
        "Return only the rewritten question, nothing else."
    )
    user_text = (
        f"Conversation history:\n{history_text}\n\nFollow-up question: {question}"
    )
    resolved = await _llm_transform(system_instruction, user_text)
    if resolved is None:
        return question
    return resolved


async def transform_query(
    question: str, history: list[dict] | None = None
) -> QueryTransformResult:
    if not config.QUERY_TRANSFORMATION_ENABLED:
        return QueryTransformResult(
            queries=[question],
            original_query=question,
        )

    # When recent session history is available, resolve any follow-up references
    # into a standalone question before applying the retrieval strategy.
    effective_question = question
    history_resolved_query: str | None = None
    if history:
        effective_question = await _resolve_to_standalone(question, history)
        if effective_question != question:
            history_resolved_query = effective_question

    strategy = config.QUERY_TRANSFORMATION_STRATEGY
    if strategy == "rewrite":
        queries = [await rewrite_query(effective_question)]
    elif strategy == "expand":
        queries = await expand_query(effective_question)
    elif strategy == "stepback":
        queries = await stepback_query(effective_question)
    else:
        logger.warning(
            "Unknown QUERY_TRANSFORMATION_STRATEGY=%r; returning original question unchanged",
            strategy,
        )
        return QueryTransformResult(
            queries=[question],
            original_query=question,
            history_resolved_query=history_resolved_query,
        )

    return QueryTransformResult(
        queries=queries,
        original_query=question,
        history_resolved_query=history_resolved_query,
        transformation_strategy=strategy,
    )

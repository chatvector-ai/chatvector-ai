"""Query transformation for retrieval (rewrite, expand, step-back)."""

import logging
import re
import time
from dataclasses import dataclass

from core.config import config
from services.history_config import HISTORY_PREVIEW_CHARS, HistoryObservation, HistoryResolutionPolicy
from services.providers import get_llm_provider
from services.retrieval_config import EffectiveRetrievalConfig

logger = logging.getLogger(__name__)

_TRANSFORM_TEMPERATURE = 0.1


@dataclass(frozen=True)
class QueryTransformResult:
    """Query transformation output for retrieval and optional debug traces."""

    queries: list[str]
    original_query: str
    history_resolved_query: str | None = None
    transformation_strategy: str | None = None
    history_trace: dict | None = None

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
        if self.history_trace:
            payload.update(self.history_trace)
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
        "Return only the rewritten query as plain text. Do not include any prefix, "
        "explanation, numbering, or quotation marks."
    )
    rewritten = await _llm_transform(system_instruction, question)
    if rewritten is None:
        return question
    return rewritten


_LIST_MARKER_PATTERN = re.compile(r"^[\d]+[.)]\s*|^[-*]\s+")


def _strip_list_marker(line: str) -> str:
    """Remove common leading list markers such as 1., 1), -, or *."""
    return _LIST_MARKER_PATTERN.sub("", line.strip()).strip()


def _collect_unique_alternatives(question: str, lines: list[str]) -> list[str]:
    """Return up to two unique alternatives, excluding the original query."""
    normalized_original = question.casefold()
    seen: set[str] = {normalized_original}
    alternatives: list[str] = []

    for line in lines:
        cleaned = _strip_list_marker(line)
        if not cleaned:
            continue

        normalized = cleaned.casefold()
        if normalized in seen:
            continue

        seen.add(normalized)
        alternatives.append(cleaned)
        if len(alternatives) == 2:
            break

    return alternatives


async def expand_query(question: str) -> list[str]:
    system_instruction = (
        "You are a query expansion assistant. Generate exactly 2 alternative phrasings "
        "of the following question for semantic search. Return only the alternatives, "
        "one per line, no numbering, no explanation."
    )
    raw = await _llm_transform(system_instruction, question)
    if raw is None:
        return [question]

    lines = [line for line in raw.splitlines() if line.strip()]
    alternatives = _collect_unique_alternatives(question, lines)
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
    broader = broader.strip()
    if not broader or broader.casefold() == question.strip().casefold():
        return [question]
    return [question, broader]


def _format_history_context(history: list[dict]) -> str:
    """Render session history as a conversational context string.

    History arrives in chronological order (oldest first).
    """
    lines: list[str] = []
    for msg in history:
        role = msg.get("role", "")
        content = (msg.get("content") or "").strip()
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
    return "\n".join(lines)


@dataclass(frozen=True)
class StandaloneResolutionCall:
    """One standalone-resolution LLM attempt."""

    query: str
    failed: bool
    latency_ms: int


async def _call_standalone_resolution(
    question: str, history: list[dict]
) -> StandaloneResolutionCall:
    """Call the resolution LLM. On failure, return the original question.

    Callers must not invoke this for every session turn. The Phase 4 gate
    (``question_needs_history_resolution``) decides when a follow-up is worth
    the extra latency and token cost. A failed, timed-out, or empty response
    falls back to ``question`` and does not fail the chat.
    """
    history_text = _format_history_context(history)
    system_instruction = (
        "You are a query resolution assistant. Given a conversation history and a "
        "follow-up question, rewrite the follow-up as a complete standalone question "
        "that does not rely on context from the conversation. Resolve pronouns "
        '("it", "they", "that", "she"), references ("the second option", '
        '"the earlier plan", "that clause"), and omitted subjects by substituting '
        "the prior entity they refer to. When the current question introduces a "
        "named entity, keep that entity. Do not replace it with an entity that "
        "appears only in prior turns. Preserve ordinals and the relation being "
        "asked about; that relation is what the user is asking, not a nearby fact "
        "from history. If the question is already standalone, return it unchanged. "
        "Return only the rewritten question, nothing else."
    )
    user_text = (
        f"Conversation history:\n{history_text}\n\nFollow-up question: {question}"
    )
    started = time.perf_counter()
    resolved = await _llm_transform(system_instruction, user_text)
    latency_ms = int((time.perf_counter() - started) * 1000)
    if resolved is None:
        return StandaloneResolutionCall(query=question, failed=True, latency_ms=latency_ms)
    return StandaloneResolutionCall(query=resolved, failed=False, latency_ms=latency_ms)


async def _resolve_to_standalone(question: str, history: list[dict]) -> str:
    """Rewrite a follow-up into a standalone query, or return it unchanged.

    Latency/cost: one extra LLM call. Phase 4 chat passes a resolution policy
    so this runs only when the need-resolution gate selects it (or when Phase 3
    coupling is restored and query transformation is enabled). The history
    window defaults to QUERY_TRANSFORMATION_HISTORY_WINDOW (6 messages).
    """
    return (await _call_standalone_resolution(question, history)).query


# v1 need-resolution gate.
#
# An extra standalone-resolution LLM call is allowed only when this gate
# returns True. Prefer resolution when the question is ambiguous.
#
# Skip the LLM when:
# - the history window is empty after filtering (caller passes an empty list)
# - the question is already standalone: no unresolved reference, and it either
#   names a subject or is long enough to be a full query
# - an explicit topic-switch cue is present and the question is otherwise
#   standalone (cues do not override pronouns, demonstratives, elliptical
#   patterns, or other referential cues)
#
# Unresolved references (case-insensitive, word boundaries):
# - pronouns: it, they, them, their, theirs, he, she, him, her, his, hers, its
# - demonstratives this/that/these/those, including determiner uses that
#   point at prior conversation ("that clause", "this section", "those terms")
# - elliptical patterns: "what about …", "how about …", "and the …",
#   "and what …", "and how …", "what else …", "tell me more …",
#   "more about …", and "how much was that"
# - one-anaphora and discourse cues: "which one", "second one", "other one",
#   "the latter", "the former", "going back", and "I meant".
#   The substring "second" inside "secondary" is not a cue.
#
# Topic-switch cues (conservative; ignored when a reference is also present):
# new topic, switch/switching topic(s), change of subject, changing the
# subject, different question, unrelated question, forget the previous,
# ignore the previous, ignore previous context, starting over.
#
# Length: 6 or more words, or 4 or more words ending in "?", with none of the
# reference signals above, is standalone. Those cutoffs are unchanged.
# Shorter fragments resolve only when every word is closed-class ("Why?",
# "Can you tell me"). A shorter question with an open-class word already
# names a subject ("Explain the indemnification clause.", "Who approves
# expenses?") and is standalone. That check is a lexicon lookup, not a new
# word-count cutoff and not a syntactic subject parse.
_ANAPHORA_RE = re.compile(
    r"\b(?:it|they|them|their|theirs|he|she|him|her|his|hers|its)\b",
    re.IGNORECASE,
)
_DEMONSTRATIVE_RE = re.compile(
    r"\b(?:this|that|these|those)\b",
    re.IGNORECASE,
)
_ELLIPTICAL_RE = re.compile(
    r"(?:^(?:what about|how about|and the|and what|and how|what else|tell me more|more about)\b"
    r"|\bhow much was that\b)",
    re.IGNORECASE,
)
# Referential follow-ups that are not pronouns, demonstratives, or ellipsis.
# Word boundaries keep "secondary" from matching "second".
_REFERENTIAL_RE = re.compile(
    r"\bwhich\s+ones?\b"
    r"|\bsecond\s+ones?\b"
    r"|\bother\s+ones?\b"
    r"|\bthe\s+latter\b"
    r"|\bthe\s+former\b"
    r"|\bgoing\s+back\b"
    r"|\bi\s+meant\b",
    re.IGNORECASE,
)
_TOPIC_SWITCH_RE = re.compile(
    r"\b(?:new topic|switch(?:ing)? topics?|change of subject|changing the subject|"
    r"different question|unrelated question|forget the previous|ignore the previous|"
    r"ignore previous context|starting over)\b",
    re.IGNORECASE,
)
_STANDALONE_MIN_WORDS = 6
_STANDALONE_MIN_QUESTION_WORDS = 4
# Function words and bare follow-up frames. A token outside this set is an
# open-class word and counts as naming a subject. Anaphoric cues are handled
# by the reference patterns above, before this set is consulted.
_CLOSED_CLASS_WORDS = frozenset(
    {
        "a",
        "about",
        "again",
        "also",
        "am",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "describe",
        "did",
        "do",
        "does",
        "else",
        "explain",
        "for",
        "former",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "here",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "latter",
        "many",
        "may",
        "me",
        "might",
        "more",
        "much",
        "must",
        "my",
        "no",
        "nor",
        "not",
        "now",
        "of",
        "ok",
        "okay",
        "on",
        "one",
        "ones",
        "or",
        "other",
        "our",
        "over",
        "please",
        "second",
        "shall",
        "she",
        "should",
        "show",
        "so",
        "tell",
        "than",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "to",
        "too",
        "under",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "whose",
        "why",
        "will",
        "with",
        "would",
        "yes",
        "you",
        "your",
    }
)
_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def _has_unresolved_demonstrative(question: str) -> bool:
    return bool(_DEMONSTRATIVE_RE.search(question))


def _has_open_class_word(question: str) -> bool:
    """Return whether the question contains a word outside the closed class."""
    for token in _WORD_RE.findall(question):
        for part in token.lower().split("'"):
            if part and part not in _CLOSED_CLASS_WORDS:
                return True
    return False


def question_needs_history_resolution(question: str, history: list[dict]) -> tuple[bool, str | None]:
    """Return whether the gate wants an LLM resolution call, and a skip reason.

    Skip reasons: ``empty_history``, ``standalone_question``, ``topic_switch``.
    """
    if not history:
        return False, "empty_history"
    text = (question or "").strip()
    if not text:
        return False, "standalone_question"

    has_reference = bool(
        _ANAPHORA_RE.search(text)
        or _has_unresolved_demonstrative(text)
        or _ELLIPTICAL_RE.search(text)
        or _REFERENTIAL_RE.search(text)
    )
    if has_reference:
        return True, None
    if _TOPIC_SWITCH_RE.search(text):
        return False, "topic_switch"

    words = text.split()
    if len(words) >= _STANDALONE_MIN_WORDS or (
        text.endswith("?") and len(words) >= _STANDALONE_MIN_QUESTION_WORDS
    ):
        return False, "standalone_question"
    if _has_open_class_word(text):
        return False, "standalone_question"
    return True, None


def _preview_messages(messages: list[dict]) -> tuple[list[dict], bool]:
    previews: list[dict] = []
    truncated = False
    for msg in messages:
        content = msg.get("content") or ""
        if len(content) > HISTORY_PREVIEW_CHARS:
            truncated = True
            content = content[:HISTORY_PREVIEW_CHARS]
        previews.append({"role": msg.get("role") or "", "content_preview": content})
    return previews, truncated


def _history_trace_payload(
    observation: HistoryObservation,
    *,
    applied: bool,
    skipped_reason: str | None,
    fallback_reason: str | None,
    latency_ms: int | None,
) -> dict:
    """Flat history fields for retrieval_debug. Names match issue 503."""
    previews, preview_truncated = _preview_messages(observation.considered)
    truncation: dict = {
        "retrieval_messages_dropped": observation.retrieval_messages_dropped,
        "generation_messages_dropped": observation.generation_messages_dropped,
        "generation_chars_truncated": observation.generation_chars_truncated,
        "preview_truncated": preview_truncated,
        "max_context_chars": observation.max_context_chars,
    }
    if observation.max_generation_history_chars is not None:
        truncation["max_generation_history_chars"] = observation.max_generation_history_chars
    payload: dict = {
        "history_considered": previews,
        "history_resolution_applied": applied,
        "history_window": {
            "retrieval": observation.retrieval_messages_used,
            "generation": observation.generation_messages_used,
        },
        "history_truncation": truncation,
    }
    if skipped_reason:
        payload["history_resolution_skipped_reason"] = skipped_reason
    if fallback_reason:
        payload["history_resolution_fallback_reason"] = fallback_reason
    if latency_ms is not None:
        payload["history_resolution_latency_ms"] = latency_ms
    if observation.config_applied:
        payload["history_config_applied"] = observation.config_applied
    return payload


def _observation_for(
    history: list[dict] | None,
    observation: HistoryObservation | None,
    *,
    considered: list[dict],
) -> HistoryObservation:
    if observation is not None:
        return observation
    messages = list(history or [])
    return HistoryObservation(
        considered=considered,
        retrieval_messages_used=len(considered),
        generation_messages_used=0,
        retrieval_messages_dropped=max(0, len(messages) - len(considered)),
        generation_messages_dropped=0,
        generation_chars_truncated=False,
        config_applied=None,
        max_context_chars=0,
        max_generation_history_chars=None,
    )


async def _resolve_with_policy(
    question: str,
    history: list[dict] | None,
    policy: HistoryResolutionPolicy,
    observation: HistoryObservation | None,
) -> tuple[str, str | None, dict]:
    """Apply a resolution policy. Returns question, resolved text, debug trace.

    ``history_resolution_applied`` is true only when the resolution LLM ran and
    returned a non-empty string. A successful call that echoes the original
    wording still counts as applied; ``history_resolved_query`` is omitted
    later when the text did not change. Gate skips and LLM failures are not
    applied. Failures set ``history_resolution_fallback_reason`` to
    ``llm_failure`` and keep the original question for retrieval.
    """
    messages = list(history or [])
    if not policy.run:
        trace = _history_trace_payload(
            _observation_for(messages, observation, considered=[]),
            applied=False,
            skipped_reason=policy.forced_skip_reason or "disabled",
            fallback_reason=None,
            latency_ms=None,
        )
        return question, None, trace

    if not messages:
        trace = _history_trace_payload(
            _observation_for(messages, observation, considered=[]),
            applied=False,
            skipped_reason="empty_history",
            fallback_reason=None,
            latency_ms=None,
        )
        return question, None, trace

    if policy.use_gate:
        needs, skip_reason = question_needs_history_resolution(question, messages)
        if not needs:
            trace = _history_trace_payload(
                _observation_for(messages, observation, considered=messages),
                applied=False,
                skipped_reason=skip_reason,
                fallback_reason=None,
                latency_ms=None,
            )
            return question, None, trace

    call = await _call_standalone_resolution(question, messages)
    if call.failed:
        trace = _history_trace_payload(
            _observation_for(messages, observation, considered=messages),
            applied=False,
            skipped_reason=None,
            fallback_reason="llm_failure",
            latency_ms=call.latency_ms,
        )
        return question, None, trace

    resolved = call.query if call.query != question else None
    trace = _history_trace_payload(
        _observation_for(messages, observation, considered=messages),
        applied=True,
        skipped_reason=None,
        fallback_reason=None,
        latency_ms=call.latency_ms,
    )
    return call.query, resolved, trace


async def transform_query(
    question: str,
    history: list[dict] | None = None,
    *,
    effective_config: EffectiveRetrievalConfig | None = None,
    resolution_policy: HistoryResolutionPolicy | None = None,
    history_observation: HistoryObservation | None = None,
) -> QueryTransformResult:
    """Transform a question for retrieval.

    When ``effective_config`` is provided, enablement and strategy come from
    that request-scoped config and the process flags are not consulted.
    Omitted config keeps the process-wide ``QUERY_TRANSFORMATION_*`` behavior.

    Standalone resolution is independent of rewrite / expand / step-back.
    When ``resolution_policy`` is omitted, resolution stays coupled to
    transformation enablement (Phase 3: resolve whenever that flag is on and
    history is non-empty). Chat passes a policy so Phase 4 can resolve a
    gated follow-up even when ``QUERY_TRANSFORMATION_ENABLED`` is false, and
    so strategies never turn on from history defaults alone.
    """
    if effective_config is None:
        enabled = config.QUERY_TRANSFORMATION_ENABLED
        strategy = config.QUERY_TRANSFORMATION_STRATEGY
        apply_strategy = bool(enabled)
    else:
        enabled = effective_config.query_transformation_enabled
        strategy = effective_config.query_transformation_strategy
        apply_strategy = effective_config.apply_query_strategy

    history_trace: dict | None = None
    if resolution_policy is None:
        if not enabled:
            return QueryTransformResult(
                queries=[question],
                original_query=question,
            )
        effective_question = question
        history_resolved_query: str | None = None
        if history:
            effective_question = await _resolve_to_standalone(question, history)
            if effective_question != question:
                history_resolved_query = effective_question
    else:
        effective_question, history_resolved_query, history_trace = await _resolve_with_policy(
            question,
            history,
            resolution_policy,
            history_observation,
        )

    if not apply_strategy or strategy == "none":
        return QueryTransformResult(
            queries=[effective_question],
            original_query=question,
            history_resolved_query=history_resolved_query,
            history_trace=history_trace,
        )

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
            history_trace=history_trace,
        )

    return QueryTransformResult(
        queries=queries,
        original_query=question,
        history_resolved_query=history_resolved_query,
        transformation_strategy=strategy,
        history_trace=history_trace,
    )

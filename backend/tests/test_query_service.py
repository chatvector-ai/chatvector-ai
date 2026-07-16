"""Tests for query transformation strategies."""

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest

import services.query_service as query_service_mod
from core.config import config
from services.query_service import (
    _format_history_context,
    _resolve_to_standalone,
    expand_query,
    rewrite_query,
    stepback_query,
    transform_query,
)


def test_transform_query_returns_original_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "expand")

    result = asyncio.run(transform_query("original question"))

    assert result.queries == ["original question"]


@pytest.mark.asyncio
async def test_rewrite_strategy_returns_single_transformed_query(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "retrieval friendly version"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("user question")

    assert result.queries == ["retrieval friendly version"]


@pytest.mark.asyncio
async def test_expand_strategy_returns_original_plus_two_alternatives(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "expand")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "first alt\nsecond alt"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("base q")

    assert result.queries == ["base q", "first alt", "second alt"]


@pytest.mark.asyncio
async def test_stepback_strategy_returns_original_and_broader_question(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "stepback")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "What are the general principles of X?"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("specific detail about X?")

    assert result.queries == [
        "specific detail about X?",
        "What are the general principles of X?",
    ]


@pytest.mark.asyncio
async def test_rewrite_degrades_on_llm_failure(monkeypatch):
    monkeypatch.setattr(
        query_service_mod,
        "_llm_transform",
        AsyncMock(return_value=None),
    )

    result = await rewrite_query("fallback me")

    assert result == "fallback me"


@pytest.mark.asyncio
async def test_expand_degrades_on_llm_failure(monkeypatch):
    monkeypatch.setattr(
        query_service_mod,
        "_llm_transform",
        AsyncMock(return_value=None),
    )

    result = await expand_query("only me")

    assert result == ["only me"]


@pytest.mark.asyncio
async def test_stepback_degrades_on_llm_failure(monkeypatch):
    monkeypatch.setattr(
        query_service_mod,
        "_llm_transform",
        AsyncMock(return_value=None),
    )

    result = await stepback_query("solo")

    assert result == ["solo"]


def test_unknown_strategy_logs_warning_and_returns_original(caplog, monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "not-a-real-strategy")

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(transform_query("unchanged"))

    assert result.queries == ["unchanged"]
    assert "Unknown QUERY_TRANSFORMATION_STRATEGY" in caplog.text


# ---------------------------------------------------------------------------
# History-aware query transformation (Issue #337)
# ---------------------------------------------------------------------------

_SAMPLE_HISTORY = [
    {"role": "assistant", "content": "Option A is fast; Option B is cheap."},
    {"role": "user", "content": "What are the options?"},
]


def test_format_history_context_chronological_order():
    """History (DESC from DB) must be reversed to chronological order in the prompt."""
    result = _format_history_context(_SAMPLE_HISTORY)
    lines = result.splitlines()
    assert lines[0].startswith("User:")
    assert lines[1].startswith("Assistant:")


def test_format_history_context_empty():
    assert _format_history_context([]) == ""


def test_format_history_context_skips_unknown_roles():
    history = [
        {"role": "system", "content": "ignored"},
        {"role": "user", "content": "hello"},
    ]
    result = _format_history_context(history)
    assert "system" not in result
    assert "ignored" not in result
    assert "User: hello" in result


@pytest.mark.asyncio
async def test_resolve_to_standalone_pronoun_resolution(monkeypatch):
    """Pronouns should be resolved to explicit referents from conversation history."""
    history = [
        {"role": "assistant", "content": "The Eiffel Tower is in Paris, France."},
        {"role": "user", "content": "Where is the Eiffel Tower?"},
    ]

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        assert "Paris" in user_text or "Eiffel" in user_text
        return "What language do people speak in France?"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await _resolve_to_standalone("What language do they speak?", history)
    assert result == "What language do people speak in France?"


@pytest.mark.asyncio
async def test_resolve_to_standalone_reference_to_previous_turn(monkeypatch):
    """References such as 'the second option' must be resolved to an explicit noun."""
    history = [
        {"role": "assistant", "content": "Option A is fast; Option B is cheap."},
        {"role": "user", "content": "What are the options?"},
    ]

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "Tell me more about Option B."

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await _resolve_to_standalone("Tell me more about the second option.", history)
    assert result == "Tell me more about Option B."


@pytest.mark.asyncio
async def test_resolve_to_standalone_followup_comparison(monkeypatch):
    """Follow-up comparisons must reference both subjects explicitly."""
    history = [
        {"role": "assistant", "content": "Plan X costs $10; Plan Y costs $20."},
        {"role": "user", "content": "What are the plans?"},
    ]

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "How does Plan X compare with Plan Y in terms of cost?"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await _resolve_to_standalone("How does that compare with the earlier plan?", history)
    assert result == "How does Plan X compare with Plan Y in terms of cost?"


@pytest.mark.asyncio
async def test_resolve_to_standalone_degrades_on_llm_failure(monkeypatch):
    """If the LLM call fails, the original question is returned unchanged."""
    monkeypatch.setattr(
        query_service_mod, "_llm_transform", AsyncMock(return_value=None)
    )

    result = await _resolve_to_standalone("What about it?", _SAMPLE_HISTORY)
    assert result == "What about it?"


@pytest.mark.asyncio
async def test_transform_query_with_history_resolves_before_strategy(monkeypatch):
    """When history is provided, _resolve_to_standalone must run before the strategy."""
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")

    resolved_question = "What are the disadvantages of Option B?"

    async def fake_resolve(question: str, history: list[dict]) -> str:
        return resolved_question

    async def fake_rewrite(question: str) -> str:
        assert question == resolved_question, "rewrite must receive the resolved question"
        return "Disadvantages of Option B"

    monkeypatch.setattr(query_service_mod, "_resolve_to_standalone", fake_resolve)
    monkeypatch.setattr(query_service_mod, "rewrite_query", fake_rewrite)

    result = await transform_query("What were its disadvantages?", history=_SAMPLE_HISTORY)

    assert result.queries == ["Disadvantages of Option B"]


@pytest.mark.asyncio
async def test_transform_query_with_empty_history_skips_resolve(monkeypatch):
    """Empty history list must not trigger _resolve_to_standalone."""
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")

    resolve_called = False

    async def fake_resolve(question: str, history: list[dict]) -> str:
        nonlocal resolve_called
        resolve_called = True
        return question

    async def fake_rewrite(question: str) -> str:
        return "rewritten"

    monkeypatch.setattr(query_service_mod, "_resolve_to_standalone", fake_resolve)
    monkeypatch.setattr(query_service_mod, "rewrite_query", fake_rewrite)

    await transform_query("standalone question", history=[])

    assert not resolve_called


@pytest.mark.asyncio
async def test_transform_query_with_none_history_skips_resolve(monkeypatch):
    """None history must not trigger _resolve_to_standalone."""
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")

    resolve_called = False

    async def fake_resolve(question: str, history: list[dict]) -> str:
        nonlocal resolve_called
        resolve_called = True
        return question

    async def fake_rewrite(question: str) -> str:
        return "rewritten"

    monkeypatch.setattr(query_service_mod, "_resolve_to_standalone", fake_resolve)
    monkeypatch.setattr(query_service_mod, "rewrite_query", fake_rewrite)

    await transform_query("standalone question", history=None)

    assert not resolve_called


def test_transform_query_disabled_ignores_history(monkeypatch):
    """When QUERY_TRANSFORMATION_ENABLED is False, history must be ignored entirely."""
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)

    result = asyncio.run(
        transform_query("follow-up question", history=_SAMPLE_HISTORY)
    )

    assert result.queries == ["follow-up question"]


@pytest.mark.asyncio
async def test_transform_query_history_passed_to_expand_strategy(monkeypatch):
    """History resolution should also apply before the expand strategy."""
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "expand")

    resolved = "What are the risks of Option A?"

    async def fake_resolve(question: str, history: list[dict]) -> str:
        return resolved

    async def fake_expand(question: str) -> list[str]:
        assert question == resolved
        return [resolved, "Risks associated with Option A", "Option A drawbacks"]

    monkeypatch.setattr(query_service_mod, "_resolve_to_standalone", fake_resolve)
    monkeypatch.setattr(query_service_mod, "expand_query", fake_expand)

    result = await transform_query("What are its risks?", history=_SAMPLE_HISTORY)

    assert result.queries[0] == resolved
    assert len(result.queries) == 3


@pytest.mark.asyncio
async def test_transform_query_history_passed_to_stepback_strategy(monkeypatch):
    """History resolution should also apply before the stepback strategy."""
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "stepback")

    resolved = "What is the cost of Option B?"

    async def fake_resolve(question: str, history: list[dict]) -> str:
        return resolved

    async def fake_stepback(question: str) -> list[str]:
        assert question == resolved
        return [resolved, "What factors determine pricing of software plans?"]

    monkeypatch.setattr(query_service_mod, "_resolve_to_standalone", fake_resolve)
    monkeypatch.setattr(query_service_mod, "stepback_query", fake_stepback)

    result = await transform_query("How much does it cost?", history=_SAMPLE_HISTORY)

    assert result.queries[0] == resolved
    assert len(result.queries) == 2


# ---------------------------------------------------------------------------
# Retrieval debug traces (Issue #392)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rewrite_strategy_retrieval_debug_shape(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "rewritten for search"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("user question")

    debug = result.to_retrieval_debug()
    assert debug == {
        "original_query": "user question",
        "transformed_queries": ["rewritten for search"],
        "transformation_strategy": "rewrite",
    }


@pytest.mark.asyncio
async def test_expand_strategy_retrieval_debug_shape(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "expand")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "alt one\nalt two"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("base q")

    debug = result.to_retrieval_debug()
    assert debug == {
        "original_query": "base q",
        "transformed_queries": ["base q", "alt one", "alt two"],
        "transformation_strategy": "expand",
    }


@pytest.mark.asyncio
async def test_stepback_strategy_retrieval_debug_shape(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "stepback")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "What are the general principles?"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("specific detail?")

    debug = result.to_retrieval_debug()
    assert debug == {
        "original_query": "specific detail?",
        "transformed_queries": ["specific detail?", "What are the general principles?"],
        "transformation_strategy": "stepback",
    }


@pytest.mark.asyncio
async def test_retrieval_debug_includes_history_resolved_query(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")

    async def fake_resolve(question: str, history: list[dict]) -> str:
        return "What are the risks of Option B?"

    async def fake_rewrite(question: str) -> str:
        return "Option B risks"

    monkeypatch.setattr(query_service_mod, "_resolve_to_standalone", fake_resolve)
    monkeypatch.setattr(query_service_mod, "rewrite_query", fake_rewrite)

    result = await transform_query("What are its risks?", history=_SAMPLE_HISTORY)

    debug = result.to_retrieval_debug()
    assert debug["original_query"] == "What are its risks?"
    assert debug["history_resolved_query"] == "What are the risks of Option B?"
    assert debug["transformed_queries"] == ["Option B risks"]
    assert debug["transformation_strategy"] == "rewrite"


def test_retrieval_debug_omits_strategy_when_transformation_disabled(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)

    result = asyncio.run(transform_query("plain question"))

    debug = result.to_retrieval_debug()
    assert debug == {
        "original_query": "plain question",
        "transformed_queries": ["plain question"],
    }

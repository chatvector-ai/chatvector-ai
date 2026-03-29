"""Tests for query transformation strategies."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

import services.query_service as query_service_mod
from core.config import config
from services.query_service import (
    expand_query,
    rewrite_query,
    stepback_query,
    transform_query,
)


def test_transform_query_returns_original_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "expand")

    result = asyncio.run(transform_query("original question"))

    assert result == ["original question"]


@pytest.mark.asyncio
async def test_rewrite_strategy_returns_single_transformed_query(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "retrieval friendly version"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("user question")

    assert result == ["retrieval friendly version"]


@pytest.mark.asyncio
async def test_expand_strategy_returns_original_plus_two_alternatives(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "expand")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "first alt\nsecond alt"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("base q")

    assert result == ["base q", "first alt", "second alt"]


@pytest.mark.asyncio
async def test_stepback_strategy_returns_original_and_broader_question(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "stepback")

    async def fake_llm(system_instruction: str, user_text: str) -> str | None:
        return "What are the general principles of X?"

    monkeypatch.setattr(query_service_mod, "_llm_transform", fake_llm)

    result = await transform_query("specific detail about X?")

    assert result == [
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

    assert result == ["unchanged"]
    assert "Unknown QUERY_TRANSFORMATION_STRATEGY" in caplog.text

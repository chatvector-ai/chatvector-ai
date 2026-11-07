"""Gated history resolution for chat, stream, batch, and eval."""

import json
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.auth import AuthContext
from core.config import config
from services.eval_config import EffectiveRetrievalConfig
from services.eval_fixtures import EvalDataset, EvalQuery, load_dataset
from services.eval_service import run_eval
from services.history_config import HistoryResolutionPolicy
from services.chat_service import (
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
)
from services.query_service import (
    QueryTransformResult,
    StandaloneResolutionCall,
    _call_standalone_resolution,
    question_needs_history_resolution,
    transform_query,
)

TEST_AUTH = AuthContext(tenant_id="dev")


def _patch_process_flags(monkeypatch, **flags: object) -> None:
    """Set process flags on every Settings instance this suite can observe.

    Earlier tests call ``importlib.reload(core.config)``, which replaces
    ``core.config.config``. Module-level ``from core.config import config``
    bindings keep the previous instance, and ``HistoryProcessDefaults.from_process``
    imports the live one.
    """
    import core.config as config_module
    import services.chat_service as chat_service_mod
    import services.query_service as query_service_mod

    targets = (
        config,
        config_module.config,
        chat_service_mod.config,
        query_service_mod.config,
    )
    seen: set[int] = set()
    for target in targets:
        if id(target) in seen:
            continue
        seen.add(id(target))
        for name, value in flags.items():
            monkeypatch.setattr(target, name, value)
_HISTORY = [
    {"role": "user", "content": "Summarize the liability section of the agreement."},
    {"role": "assistant", "content": "The liability section limits damages."},
]
_PRONOUN = "What does it say about liability?"
_WHAT_ABOUT = "What about the second clause?"
_STANDALONE = "What is the liability clause in section 4 of the master agreement?"
_TOPIC_SWITCH = "New topic: What is the refund policy for cancelled annual plans?"
_RESOLVED = "What does the agreement say about liability?"


def test_gate_runs_for_pronouns_and_elliptical_followups():
    assert question_needs_history_resolution(_PRONOUN, _HISTORY) == (True, None)
    assert question_needs_history_resolution(_WHAT_ABOUT, _HISTORY) == (True, None)
    assert question_needs_history_resolution("How much was that?", _HISTORY) == (True, None)
    assert question_needs_history_resolution("And the termination clause?", _HISTORY) == (True, None)
    assert question_needs_history_resolution(
        "What does she require of the customer?",
        _HISTORY,
    ) == (True, None)


def test_gate_runs_for_demonstrative_followups():
    assert question_needs_history_resolution("What does that clause require?", _HISTORY) == (
        True,
        None,
    )
    assert question_needs_history_resolution("How does this section work?", _HISTORY) == (
        True,
        None,
    )
    assert question_needs_history_resolution("Can you explain those terms?", _HISTORY) == (
        True,
        None,
    )


def test_gate_skips_standalone_topic_switch_and_empty_history():
    assert question_needs_history_resolution(_STANDALONE, _HISTORY) == (
        False,
        "standalone_question",
    )
    assert question_needs_history_resolution(
        "How does the arbitration clause work under California law?",
        _HISTORY,
    ) == (False, "standalone_question")
    assert question_needs_history_resolution(_TOPIC_SWITCH, _HISTORY) == (False, "topic_switch")
    assert question_needs_history_resolution(_PRONOUN, []) == (False, "empty_history")
    # A topic cue does not override an unresolved pronoun.
    mixed = "New topic: what does it say about fees?"
    assert question_needs_history_resolution(mixed, _HISTORY)[0] is True


def test_gate_runs_for_referential_followups():
    referential = (
        "What does the second one require?",
        "Which one has the lower cancellation penalty?",
        "What does the latter agreement require of the customer?",
        "What does the former agreement require of the customer?",
        "What does the other one require from the customer?",
        "Going back to the renewal clause, what is the notice period?",
        "No, I meant the enterprise agreement.",
        "Why?",
    )
    for question in referential:
        assert question_needs_history_resolution(question, _HISTORY) == (True, None)


def test_gate_does_not_treat_secondary_substring_as_a_reference():
    assert question_needs_history_resolution(
        "What is the secondary liability cap in the master services agreement?",
        _HISTORY,
    ) == (False, "standalone_question")
    assert question_needs_history_resolution(_STANDALONE, _HISTORY) == (
        False,
        "standalone_question",
    )


def test_gate_empty_history_skips_referential_question():
    assert question_needs_history_resolution(
        "Which one has the lower cancellation penalty?",
        [],
    ) == (False, "empty_history")
    assert question_needs_history_resolution("No, I meant the enterprise agreement.", []) == (
        False,
        "empty_history",
    )


def test_gate_topic_switch_does_not_override_which_one():
    assert question_needs_history_resolution(
        "New topic: which one is cheaper?",
        _HISTORY,
    ) == (True, None)


def test_gate_skips_short_questions_that_name_a_subject():
    assert question_needs_history_resolution(
        "Explain the indemnification clause.",
        _HISTORY,
    ) == (False, "standalone_question")
    assert question_needs_history_resolution(
        "Who approves expenses?",
        _HISTORY,
    ) == (False, "standalone_question")


def test_gate_keeps_length_thresholds_for_fragments_without_a_subject():
    """Bare fragments still resolve. The 6-word and 4-word cutoffs stay."""
    assert question_needs_history_resolution("Why not now?", _HISTORY) == (True, None)
    assert question_needs_history_resolution("How much?", _HISTORY) == (True, None)
    assert question_needs_history_resolution("Can you tell me", _HISTORY) == (True, None)


@pytest.mark.asyncio
async def test_history_preview_is_truncated(monkeypatch):
    long_history = [{"role": "user", "content": "x" * 400}]

    async def fake_llm(system_instruction: str, user_text: str) -> str:
        return "resolved follow up"

    monkeypatch.setattr("services.query_service._llm_transform", fake_llm)
    result = await transform_query(
        _PRONOUN,
        history=long_history,
        resolution_policy=HistoryResolutionPolicy(run=True, use_gate=True),
    )
    preview = result.to_retrieval_debug()["history_considered"][0]["content_preview"]
    assert len(preview) == 160
    assert result.to_retrieval_debug()["history_truncation"]["preview_truncated"] is True


@pytest.mark.asyncio
async def test_phase4_policy_resolves_followup_without_enabling_strategy(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_STRATEGY", "rewrite")

    async def fake_llm(system_instruction: str, user_text: str) -> str:
        return _RESOLVED

    async def rewrite_must_not_run(question: str) -> str:
        raise AssertionError("rewrite must not run from history defaults")

    monkeypatch.setattr("services.query_service._llm_transform", fake_llm)
    monkeypatch.setattr("services.query_service.rewrite_query", rewrite_must_not_run)

    result = await transform_query(
        _PRONOUN,
        history=_HISTORY,
        resolution_policy=HistoryResolutionPolicy(run=True, use_gate=True),
    )

    assert result.queries == [_RESOLVED]
    assert result.history_resolved_query == _RESOLVED
    assert result.transformation_strategy is None
    debug = result.to_retrieval_debug()
    assert debug["history_resolution_applied"] is True
    assert debug["history_resolution_latency_ms"] >= 0
    assert "history_resolution_skipped_reason" not in debug
    assert len(debug["history_considered"]) == len(_HISTORY)


@pytest.mark.asyncio
async def test_phase4_policy_skips_llm_for_standalone_question(monkeypatch):
    async def resolve_must_not_run(question: str, history: list[dict]) -> StandaloneResolutionCall:
        raise AssertionError("standalone question must not call the resolution LLM")

    monkeypatch.setattr("services.query_service._call_standalone_resolution", resolve_must_not_run)

    result = await transform_query(
        _STANDALONE,
        history=_HISTORY,
        resolution_policy=HistoryResolutionPolicy(run=True, use_gate=True),
    )

    assert result.queries == [_STANDALONE]
    debug = result.to_retrieval_debug()
    assert debug["history_resolution_applied"] is False
    assert debug["history_resolution_skipped_reason"] == "standalone_question"
    assert "history_resolution_latency_ms" not in debug


@pytest.mark.asyncio
async def test_resolution_failure_falls_back_and_records_debug(monkeypatch):
    async def fake_llm(system_instruction: str, user_text: str) -> None:
        return None

    monkeypatch.setattr("services.query_service._llm_transform", fake_llm)

    result = await transform_query(
        _PRONOUN,
        history=_HISTORY,
        resolution_policy=HistoryResolutionPolicy(run=True, use_gate=True),
    )

    assert result.queries == [_PRONOUN]
    debug = result.to_retrieval_debug()
    assert debug["history_resolution_applied"] is False
    assert debug["history_resolution_fallback_reason"] == "llm_failure"
    assert "history_resolved_query" not in debug
    assert debug["history_resolution_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_phase3_policy_always_resolves_when_transformation_enabled(monkeypatch):
    calls: list[str] = []

    async def fake_resolve(question: str, history: list[dict]) -> StandaloneResolutionCall:
        calls.append(question)
        return StandaloneResolutionCall(query=question, failed=False, latency_ms=4)

    monkeypatch.setattr("services.query_service._call_standalone_resolution", fake_resolve)

    await transform_query(
        _STANDALONE,
        history=_HISTORY,
        resolution_policy=HistoryResolutionPolicy(run=False, use_gate=False, forced_skip_reason="disabled"),
    )
    assert calls == []

    await transform_query(
        _STANDALONE,
        history=_HISTORY,
        resolution_policy=HistoryResolutionPolicy(run=True, use_gate=False),
    )
    assert calls == [_STANDALONE]


@contextmanager
def _service_patches(embed):
    with ExitStack() as stack:
        for patcher in (
            patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
            patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
            patch("services.chat_service.get_embeddings", new=embed),
            patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
            patch("db.get_session_history", new=AsyncMock(return_value=list(_HISTORY))),
            patch("db.store_chat_turn", new=AsyncMock()),
        ):
            stack.enter_context(patcher)
        yield


def _embed_capture(captured: dict):
    async def fake_embed(texts, **kwargs):
        captured["texts"] = list(texts)
        return [[0.1] for _ in texts]

    return fake_embed


@pytest.mark.asyncio
async def test_chat_pronoun_followup_resolves_when_transformation_disabled(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    captured: dict = {}

    async def fake_llm(system_instruction: str, user_text: str) -> str:
        captured["llm"] = True
        return _RESOLVED

    monkeypatch.setattr("services.query_service._llm_transform", fake_llm)
    with _service_patches(_embed_capture(captured)):
        result = await answer_question_for_document(
            question=_PRONOUN,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
        )

    assert captured["texts"] == [_RESOLVED]
    assert result["status"] == "ok"
    assert result["retrieval_debug"]["history_resolved_query"] == _RESOLVED
    assert result["retrieval_debug"]["history_resolution_applied"] is True


@pytest.mark.asyncio
async def test_chat_standalone_question_does_not_call_resolution_llm(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    captured: dict = {}

    async def resolve_must_not_run(question: str, history: list[dict]) -> StandaloneResolutionCall:
        raise AssertionError("standalone question must not call the resolution LLM")

    monkeypatch.setattr("services.query_service._call_standalone_resolution", resolve_must_not_run)
    with _service_patches(_embed_capture(captured)):
        result = await answer_question_for_document(
            question=_STANDALONE,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
        )

    assert captured["texts"] == [_STANDALONE]
    assert result["retrieval_debug"]["history_resolution_skipped_reason"] == "standalone_question"
    assert result["retrieval_debug"]["history_resolution_applied"] is False
    assert len(result["retrieval_debug"]["history_considered"]) == len(_HISTORY)
    assert result["retrieval_debug"]["history_window"]["retrieval"] == len(_HISTORY)


@pytest.mark.asyncio
async def test_chat_what_about_resolves_and_topic_switch_does_not(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    captured: dict = {"calls": 0}

    async def fake_resolve(question: str, history: list[dict]) -> StandaloneResolutionCall:
        captured["calls"] += 1
        captured["question"] = question
        return StandaloneResolutionCall(
            query="What does the second clause of the agreement say?",
            failed=False,
            latency_ms=2,
        )

    monkeypatch.setattr("services.query_service._call_standalone_resolution", fake_resolve)
    with _service_patches(_embed_capture(captured)):
        await answer_question_for_document(
            question=_WHAT_ABOUT,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
        )
    assert captured["calls"] == 1
    assert captured["texts"] == ["What does the second clause of the agreement say?"]

    captured["calls"] = 0
    with _service_patches(_embed_capture(captured)):
        await answer_question_for_document(
            question=_TOPIC_SWITCH,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
        )
    assert captured["calls"] == 0
    assert captured["texts"] == [_TOPIC_SWITCH]


@pytest.mark.asyncio
async def test_chat_resolution_failure_keeps_200_and_records_debug(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    captured: dict = {}

    async def fake_llm(system_instruction: str, user_text: str) -> None:
        return None

    monkeypatch.setattr("services.query_service._llm_transform", fake_llm)
    with _service_patches(_embed_capture(captured)):
        result = await answer_question_for_document(
            question=_PRONOUN,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
        )

    assert result["status"] == "ok"
    assert captured["texts"] == [_PRONOUN]
    assert result["retrieval_debug"]["history_resolution_fallback_reason"] == "llm_failure"
    assert "history_resolved_query" not in result["retrieval_debug"]


@pytest.mark.asyncio
async def test_history_aware_default_false_restores_phase3_gating(monkeypatch):
    _patch_process_flags(
        monkeypatch,
        HISTORY_AWARE_RETRIEVAL_DEFAULT=False,
        QUERY_TRANSFORMATION_ENABLED=False,
    )
    captured: dict = {}

    async def resolve_must_not_run(question: str, history: list[dict]) -> StandaloneResolutionCall:
        raise AssertionError("Phase 3 coupling must not resolve while transformation is off")

    monkeypatch.setattr("services.query_service._call_standalone_resolution", resolve_must_not_run)
    with _service_patches(_embed_capture(captured)):
        await answer_question_for_document(
            question=_PRONOUN,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
        )
    assert captured["texts"] == [_PRONOUN]

    _patch_process_flags(
        monkeypatch,
        HISTORY_AWARE_RETRIEVAL_DEFAULT=False,
        QUERY_TRANSFORMATION_ENABLED=True,
    )
    calls: list[str] = []

    async def fake_resolve(question: str, history: list[dict]) -> StandaloneResolutionCall:
        calls.append(question)
        return StandaloneResolutionCall(query=question, failed=False, latency_ms=1)

    monkeypatch.setattr("services.query_service._call_standalone_resolution", fake_resolve)
    monkeypatch.setattr("services.query_service._llm_transform", AsyncMock(return_value="rewritten"))
    with _service_patches(_embed_capture(captured)):
        await answer_question_for_document(
            question=_STANDALONE,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
        )
    assert calls == [_STANDALONE]


@pytest.mark.asyncio
async def test_chat_skip_history_transform_does_not_resolve(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    captured: dict = {}

    async def resolve_must_not_run(question: str, history: list[dict]) -> StandaloneResolutionCall:
        raise AssertionError("skip_history_transform must not resolve")

    monkeypatch.setattr("services.query_service._call_standalone_resolution", resolve_must_not_run)
    with _service_patches(_embed_capture(captured)):
        result = await answer_question_for_document(
            question=_PRONOUN,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
            retrieval_fields={"skip_history_transform": True},
        )

    assert captured["texts"] == [_PRONOUN]
    assert result["retrieval_debug"]["history_resolution_skipped_reason"] == "compare_skip"
    assert result["retrieval_debug"]["history_considered"] == []


@pytest.mark.asyncio
async def test_request_can_disable_resolution_and_windows_are_observable(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", True)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    full_history = [{"role": "user", "content": f"message-{i}"} for i in range(8)]
    captured: dict = {}

    async def resolve_must_not_run(question: str, history: list[dict]) -> StandaloneResolutionCall:
        raise AssertionError("explicit history_aware_retrieval=false must not resolve")

    async def fake_transform(question: str, history=None, **kwargs):
        captured["retrieval"] = history
        observation = kwargs["history_observation"]
        captured["generation_used"] = observation.generation_messages_used
        captured["config_applied"] = observation.config_applied
        return QueryTransformResult(queries=[question], original_query=question)

    def fake_context(chunks, session_context=None, **kwargs):
        captured["generation"] = list(session_context.chat_history) if session_context else []
        return "ctx"

    monkeypatch.setattr("services.query_service._call_standalone_resolution", resolve_must_not_run)
    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.get_embeddings", new=_embed_capture(captured)),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
        patch("services.chat_service.build_context_from_chunks", new=fake_context),
        patch("services.chat_service.transform_query", new=fake_transform),
        patch("db.get_session_history", new=AsyncMock(return_value=full_history)),
        patch("db.store_chat_turn", new=AsyncMock()),
    ):
        await answer_question_for_document(
            question=_PRONOUN,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
            history_fields={"history_aware_retrieval": False},
        )
        assert captured["retrieval"] is None

        await answer_question_for_document(
            question=_PRONOUN,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
            history_fields={"retrieval_history_window": 2, "generation_history_window": 4},
        )

    assert [msg["content"] for msg in captured["retrieval"]] == ["message-6", "message-7"]
    assert [msg["content"] for msg in captured["generation"]] == [
        "message-4",
        "message-5",
        "message-6",
        "message-7",
    ]
    assert captured["generation_used"] == 4
    assert captured["config_applied"]["retrieval_history_window"]["source"] == "request"


@pytest.mark.asyncio
async def test_retrieval_debug_history_considered_matches_retrieval_window(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    full_history = [{"role": "user", "content": f"message-{i}"} for i in range(8)]
    captured: dict = {}

    async def resolve_must_not_run(question: str, history: list[dict]) -> StandaloneResolutionCall:
        raise AssertionError("standalone question must not call the resolution LLM")

    monkeypatch.setattr("services.query_service._call_standalone_resolution", resolve_must_not_run)
    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.get_embeddings", new=_embed_capture(captured)),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
        patch("db.get_session_history", new=AsyncMock(return_value=full_history)),
        patch("db.store_chat_turn", new=AsyncMock()),
    ):
        result = await answer_question_for_document(
            question=_STANDALONE,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
            history_fields={"retrieval_history_window": 2},
        )

    debug = result["retrieval_debug"]
    assert [entry["content_preview"] for entry in debug["history_considered"]] == [
        "message-6",
        "message-7",
    ]
    assert debug["history_window"]["retrieval"] == 2
    assert debug["history_truncation"]["retrieval_messages_dropped"] == 6
    assert debug["history_truncation"]["max_context_chars"] > 0


@pytest.mark.asyncio
async def test_resolution_echo_omits_history_resolved_query_but_marks_applied(monkeypatch):
    async def fake_llm(system_instruction: str, user_text: str) -> str:
        return _STANDALONE

    monkeypatch.setattr("services.query_service._llm_transform", fake_llm)

    result = await transform_query(
        _STANDALONE,
        history=_HISTORY,
        resolution_policy=HistoryResolutionPolicy(run=True, use_gate=False),
    )

    debug = result.to_retrieval_debug()
    assert debug["history_resolution_applied"] is True
    assert "history_resolved_query" not in debug
    assert debug["history_resolution_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_stream_followup_uses_resolved_query(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    captured: dict = {}

    async def fake_llm(system_instruction: str, user_text: str) -> str:
        return _RESOLVED

    async def fake_stream(question, context):
        yield "token"

    provider = AsyncMock()
    provider.model_name = "test-model"
    monkeypatch.setattr("services.query_service._llm_transform", fake_llm)
    with (
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(return_value=["doc-1"])),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.get_embeddings", new=_embed_capture(captured)),
        patch("services.chat_service.generate_answer_stream", new=fake_stream),
        patch("services.providers.get_llm_provider", return_value=provider),
        patch("db.get_session_history", new=AsyncMock(return_value=list(_HISTORY))),
        patch("db.store_chat_turn", new=AsyncMock(return_value=("user-msg", "assistant-msg"))),
    ):
        async for _event in answer_question_stream_for_document(
            _PRONOUN,
            "doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
        ):
            pass

    assert captured["texts"] == [_RESOLVED]


@pytest.mark.asyncio
async def test_batch_compare_skips_history_and_multidoc_uses_it(monkeypatch):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    captured: dict = {"contexts": []}

    async def fake_resolve(question: str, history: list[dict]) -> StandaloneResolutionCall:
        return StandaloneResolutionCall(query=_RESOLVED, failed=False, latency_ms=1)

    def fake_context(chunks, session_context=None, **kwargs):
        history = list(session_context.chat_history) if session_context and session_context.chat_history else []
        captured["contexts"].append(history)
        return "ctx"

    monkeypatch.setattr("services.query_service._call_standalone_resolution", fake_resolve)
    with (
        patch(
            "services.chat_service.get_embeddings",
            new=AsyncMock(side_effect=lambda texts, **kwargs: [[0.2] for _ in texts]),
        ),
        patch("services.chat_service._resolve_retrieval_doc_ids", new=AsyncMock(side_effect=lambda **kwargs: list(kwargs["requested_doc_ids"]))),
        patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])),
        patch("services.chat_service.build_context_from_chunks", new=fake_context),
        patch("services.chat_service.generate_answer", new=AsyncMock(return_value=("ans", 1, "m"))),
        patch("db.get_session_history", new=AsyncMock(return_value=list(_HISTORY))),
        patch("db.store_chat_turn", new=AsyncMock()) as store,
    ):
        await answer_questions_for_documents_batch(
            [{"question": _PRONOUN, "doc_ids": ["doc-1"], "session_id": "sess-1"}],
            auth=TEST_AUTH,
        )
        await answer_questions_for_documents_batch(
            [{"question": _PRONOUN, "doc_ids": ["doc-1", "doc-2"], "session_id": "sess-1"}],
            auth=TEST_AUTH,
        )

    assert captured["contexts"][0] == []
    assert captured["contexts"][1]
    assert store.await_count == 1


@pytest.mark.asyncio
async def test_eval_skips_history_unless_row_requests_simulation(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    calls: list[str] = []

    async def fake_resolve(question: str, history: list[dict]) -> StandaloneResolutionCall:
        calls.append(question)
        return StandaloneResolutionCall(query=_RESOLVED, failed=False, latency_ms=1)

    monkeypatch.setattr("services.query_service._call_standalone_resolution", fake_resolve)
    dataset = EvalDataset(
        name="sessions",
        queries=[
            EvalQuery(query=_PRONOUN, doc_ids=["doc-1"], relevant_doc_ids=["doc-1"]),
            EvalQuery(
                query=_PRONOUN,
                doc_ids=["doc-1"],
                relevant_doc_ids=["doc-1"],
                simulate_session=True,
                session_history=list(_HISTORY),
            ),
        ],
    )
    arm = EffectiveRetrievalConfig(
        label="default",
        hybrid_retrieval_enabled=False,
        enable_reranking=False,
    )
    with (
        patch("services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])),
        patch(
            "services.chat_service.get_embeddings",
            new=AsyncMock(side_effect=lambda texts, **kwargs: [[0.1] for _ in texts]),
        ),
    ):
        await run_eval(dataset, [arm], tenant_id="tenant-eval")

    assert calls == [_PRONOUN]

    path = tmp_path / "eval.json"
    path.write_text(
        json.dumps(
            {
                "name": "sim",
                "queries": [
                    {
                        "query": _PRONOUN,
                        "doc_ids": ["doc-1"],
                        "relevant_doc_ids": ["doc-1"],
                        "simulate_session": True,
                        "session_history": _HISTORY,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_dataset(path)
    assert loaded.queries[0].simulate_session is True
    assert loaded.queries[0].session_history[0]["role"] == "user"


_PLAN_HISTORY = [
    {"role": "user", "content": "Compare the termination notice for Plan A and Plan B."},
    {
        "role": "assistant",
        "content": "Plan A requires 30 days notice. Plan B requires 60 days notice.",
    },
]
_ENTERPRISE_QUESTION = "What is the notice period for the enterprise termination notice?"
_ENTERPRISE_RESOLVED = "What notice period does the enterprise termination notice require?"
_MARIA_HISTORY = [
    {"role": "user", "content": "What does Maria require of the customer?"},
    {
        "role": "assistant",
        "content": "Maria requires the customer to give written notice.",
    },
]
_SHE_QUESTION = "What does she require of the customer?"
_SHE_RESOLVED = "What does Maria require of the customer?"


class _CapturingResolutionProvider:
    """Fake LLM provider. Records the resolver messages and returns one completion."""

    def __init__(self, completion: str) -> None:
        self.completion = completion
        self.calls: list[dict[str, str]] = []

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str,
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        self.calls.append({"prompt": prompt, "system_instruction": system_instruction})
        return self.completion


class _RaisingResolutionProvider:
    """Fake LLM provider whose generate call fails."""

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str,
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        raise RuntimeError("resolver unavailable")


def _patch_resolution_provider(monkeypatch, provider: object) -> None:
    monkeypatch.setattr("services.query_service.get_llm_provider", lambda: provider)


def _assert_resolution_instruction(instruction: str) -> None:
    """The inline instruction still resolves anaphora and returns only the question."""
    lowered = instruction.casefold()
    assert '"it"' in instruction
    assert '"they"' in instruction
    assert '"that"' in instruction
    assert '"she"' in instruction
    assert "that clause" in lowered
    assert "the second option" in lowered
    assert "the earlier plan" in lowered
    assert "omitted subjects" in lowered
    assert "substituting the prior entity they refer to" in lowered
    assert "if the question is already standalone, return it unchanged" in lowered
    assert "return only the rewritten question, nothing else" in lowered


def _assert_enterprise_messages(instruction: str, user_text: str) -> None:
    """Messages forbid attaching enterprise termination to Plan A or Plan B."""
    _assert_resolution_instruction(instruction)
    lowered = instruction.casefold()
    assert "when the current question introduces a named entity, keep that entity" in lowered
    assert "do not replace it with an entity that appears only in prior turns" in lowered
    assert "preserve ordinals and the relation being asked about" in lowered
    assert "not a nearby fact from history" in lowered
    history, separator, follow_up = user_text.partition("Follow-up question:")
    assert separator
    assert "Plan A" in history
    assert "Plan B" in history
    assert "enterprise termination" not in history.casefold()
    assert "enterprise termination" in follow_up.casefold()
    assert "Plan A" not in follow_up
    assert "Plan B" not in follow_up


def _assert_pronoun_messages(instruction: str, user_text: str) -> None:
    """Messages still require substituting the prior entity for a pronoun."""
    _assert_resolution_instruction(instruction)
    history, separator, follow_up = user_text.partition("Follow-up question:")
    assert separator
    assert "Maria" in history
    assert "she" in follow_up.casefold()


@pytest.mark.asyncio
async def test_resolver_keeps_introduced_enterprise_entity(monkeypatch):
    """A newly named entity and its relation stay off entities from earlier turns.

    The gate is not what this fixture exercises. The resolver is called directly
    so the prompt contract is checked whenever resolution runs.
    """
    provider = _CapturingResolutionProvider(_ENTERPRISE_RESOLVED)
    _patch_resolution_provider(monkeypatch, provider)

    call = await _call_standalone_resolution(_ENTERPRISE_QUESTION, _PLAN_HISTORY)
    result = await transform_query(
        _ENTERPRISE_QUESTION,
        history=_PLAN_HISTORY,
        resolution_policy=HistoryResolutionPolicy(run=True, use_gate=False),
    )

    assert provider.calls
    for recorded in provider.calls:
        _assert_enterprise_messages(recorded["system_instruction"], recorded["prompt"])
    assert call.failed is False
    assert call.query == _ENTERPRISE_RESOLVED
    assert result.queries == [_ENTERPRISE_RESOLVED]
    assert result.history_resolved_query == _ENTERPRISE_RESOLVED


@pytest.mark.asyncio
async def test_resolver_still_resolves_pronoun_from_history(monkeypatch):
    """A pronoun still resolves to the prior entity, and the caller keeps that rewrite."""
    provider = _CapturingResolutionProvider(_SHE_RESOLVED)
    _patch_resolution_provider(monkeypatch, provider)

    call = await _call_standalone_resolution(_SHE_QUESTION, _MARIA_HISTORY)
    result = await transform_query(
        _SHE_QUESTION,
        history=_MARIA_HISTORY,
        resolution_policy=HistoryResolutionPolicy(run=True, use_gate=True),
    )

    assert provider.calls
    for recorded in provider.calls:
        _assert_pronoun_messages(recorded["system_instruction"], recorded["prompt"])
    assert call.failed is False
    assert call.query == _SHE_RESOLVED
    assert result.queries == [_SHE_RESOLVED]
    assert result.history_resolved_query == _SHE_RESOLVED


@pytest.mark.asyncio
async def test_resolver_exception_returns_original_question(monkeypatch):
    _patch_resolution_provider(monkeypatch, _RaisingResolutionProvider())

    call = await _call_standalone_resolution(_PRONOUN, _HISTORY)

    assert call.failed is True
    assert call.query == _PRONOUN


@pytest.mark.asyncio
async def test_chat_resolver_exception_keeps_original_question(monkeypatch):
    """A resolver exception does not fail the chat request."""
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "HISTORY_AWARE_RETRIEVAL_DEFAULT", True)
    captured: dict = {}
    _patch_resolution_provider(monkeypatch, _RaisingResolutionProvider())

    with _service_patches(_embed_capture(captured)):
        result = await answer_question_for_document(
            question=_PRONOUN,
            doc_id="doc-1",
            session_id="sess-1",
            auth=TEST_AUTH,
            debug_retrieval=True,
        )

    assert result["status"] == "ok"
    assert captured["texts"] == [_PRONOUN]
    assert result["retrieval_debug"]["history_resolution_fallback_reason"] == "llm_failure"
    assert "history_resolved_query" not in result["retrieval_debug"]

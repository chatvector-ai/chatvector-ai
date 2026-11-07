"""Fixed conversation scripts stay a list of user lines.

The runner tests mock the turn player. They do not call a live provider.
"""

import inspect
import json
import sys
from types import SimpleNamespace

import pytest

from cli import cmd_eval_conversations, main
from core.config import config
from services.conversation_scenarios import (
    SCENARIO_CLASSES,
    CHECKED_IN_SCENARIOS,
    ConversationScenarioError,
    CorpusChatPlayer,
    load_scenario,
    load_scenario_directory,
    run_conversation_scenarios,
    run_checked_in_conversations,
)
import services.conversation_scenarios as conversation_scenarios


def test_checked_in_directory_has_each_scenario_class():
    scenarios = load_scenario_directory(CHECKED_IN_SCENARIOS)
    assert len(scenarios) == len(SCENARIO_CLASSES)
    assert {scenario.scenario_class for scenario in scenarios} == set(SCENARIO_CLASSES)
    by_class = {scenario.scenario_class: scenario for scenario in scenarios}
    long_session = by_class["long_session"]
    assert len(long_session.turns) >= 12
    assert long_session.max_turns >= len(long_session.turns)
    ambiguity = by_class["ambiguity"]
    contradictory = by_class["contradictory_sources"]
    assert any(turn.expected_refusal is not None for turn in ambiguity.turns)
    assert any(turn.expected_facts for turn in contradictory.turns)
    absent = by_class["absent_answer"]
    assert any(turn.expected_refusal is not None for turn in absent.turns)


def test_loader_copies_user_lines_and_does_not_add_turns():
    scenarios = load_scenario_directory(CHECKED_IN_SCENARIOS)
    for scenario in scenarios:
        raw = json.loads(scenario.source_path.read_text(encoding="utf-8"))
        assert [turn.user for turn in scenario.turns] == [row["user"] for row in raw["turns"]]
        assert len(scenario.turns) == len(raw["turns"])


def test_loader_rejects_a_field_that_would_supply_another_user_line(tmp_path):
    path = tmp_path / "extra.json"
    path.write_text(
        json.dumps(
            {
                "id": "extra-user",
                "class": "pronoun",
                "max_turns": 1,
                "logical_keys": ["hr-pto-policy"],
                "turns": [
                    {
                        "user": "How many paid days off does policy POL-HR-014 grant captains?",
                        "generated_user": "What about weekends?",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConversationScenarioError, match="unknown fields"):
        load_scenario(path)


def _manifest(*pairs: tuple[str, str]) -> dict:
    return {
        "tenant_id": "eval-tenant",
        "chunk_settings": {
            "CHUNK_SIZE": config.CHUNK_SIZE,
            "CHUNK_OVERLAP": config.CHUNK_OVERLAP,
            "CHUNKING_STRATEGY": config.CHUNKING_STRATEGY,
        },
        "documents": [
            {"logical_key": key, "document_id": doc_id} for key, doc_id in pairs
        ],
    }


def _write_script(
    tmp_path,
    turns: list[dict],
    *,
    max_turns: int,
    scenario_id: str = "two-turn",
    logical_keys: list[str] | None = None,
):
    path = tmp_path / f"{scenario_id}.json"
    path.write_text(
        json.dumps(
            {
                "id": scenario_id,
                "class": "pronoun",
                "max_turns": max_turns,
                "logical_keys": logical_keys or ["hr-pto-policy", "product-harbor-pass"],
                "turns": turns,
            }
        ),
        encoding="utf-8",
    )
    return load_scenario(path)


def _two_turn_script(tmp_path, *, max_turns: int = 2):
    return _write_script(
        tmp_path,
        [
            {
                "user": "How many paid days off does policy POL-HR-014 grant captains?",
                "resolution": "empty_history",
                "expected_facts": ["18 paid days off"],
            },
            {
                "user": "What is the fare code for the standard Harbor Pass ticket?",
                "resolution": "standalone_question",
                "expected_facts": ["HP-100"],
            },
        ],
        max_turns=max_turns,
    )


def _chat(
    answer: str,
    *,
    reason: str | None,
    applied: bool,
    resolved: str | None = None,
    original: str | None = None,
):
    debug = {
        "original_query": "stored-on-the-turn" if original is None else original,
        "history_resolution_applied": applied,
        "effective_config": {"match_count": {"value": 5, "source": "env"}},
    }
    if reason is not None:
        debug["history_resolution_skipped_reason"] = reason
    if resolved is not None:
        debug["history_resolved_query"] = resolved
    return {
        "status": "ok",
        "answer": answer,
        "model": "mock-model",
        "retrieval_debug": debug,
    }


def _player(responses: list[dict]):
    calls: list[str] = []

    async def play(user: str, *, scenario_id: str, turn_index: int) -> dict:
        calls.append(user)
        return responses[turn_index]

    play.calls = calls
    return play


def _passing_responses():
    return [
        _chat("Captains receive 18 Paid Days Off each year.", reason="empty_history", applied=False),
        _chat("The fare code is HP-100.", reason="standalone_question", applied=False),
    ]


async def _run(tmp_path, scenario, play):
    manifest = _manifest(("hr-pto-policy", "doc-pto"), ("product-harbor-pass", "doc-harbor"))
    return await run_conversation_scenarios(
        [scenario],
        manifest=manifest,
        tenant_id="eval-tenant",
        listed_document_ids=["doc-pto", "doc-harbor"],
        play_turn=play,
        artifact_dir=tmp_path / "artifacts",
        provider="mock-provider",
        configured_model="configured-model",
        persona="default",
        retrieval_config={"match_count": {"value": 5, "source": "env"}},
    )


async def test_two_turn_fixture_passes_when_fact_and_skip_reason_match(tmp_path):
    scenario = _two_turn_script(tmp_path)
    play = _player(_passing_responses())
    result = await _run(tmp_path, scenario, play)
    assert result.passed
    assert play.calls == [turn.user for turn in scenario.turns]
    artifact = json.loads(result.scenarios[0].artifact_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "passed"
    assert artifact["provider"] == "mock-provider"
    assert artifact["model"] == "mock-model"
    assert artifact["persona"] == "default"
    assert artifact["retrieval_config"] == {"match_count": {"value": 5, "source": "env"}}
    assert artifact["chunk_settings"]["CHUNK_SIZE"] == config.CHUNK_SIZE
    assert artifact["logical_keys"] == ["hr-pto-policy", "product-harbor-pass"]
    assert [turn["user"] for turn in artifact["turns"]] == play.calls
    assert artifact["turns"][0]["resolution_debug"]["history_resolution_skipped_reason"] == (
        "empty_history"
    )
    assert artifact["turns"][1]["resolution_debug"]["history_resolution_skipped_reason"] == (
        "standalone_question"
    )


async def test_two_turn_fixture_fails_when_the_fact_is_missing(tmp_path):
    scenario = _two_turn_script(tmp_path)
    play = _player(
        [
            _passing_responses()[0],
            _chat("The fare code is not stated.", reason="standalone_question", applied=False),
        ]
    )
    result = await _run(tmp_path, scenario, play)
    assert not result.passed
    assert play.calls == [turn.user for turn in scenario.turns]
    artifact = json.loads(result.scenarios[0].artifact_path.read_text(encoding="utf-8"))
    assert artifact["failing_turn_index"] == 1
    assert artifact["error"]
    assert "HP-100" in artifact["error"]


async def test_two_turn_fixture_fails_when_the_skip_reason_differs(tmp_path):
    scenario = _two_turn_script(tmp_path)
    play = _player(
        [
            _passing_responses()[0],
            _chat("The fare code is HP-100.", reason="topic_switch", applied=False),
        ]
    )
    result = await _run(tmp_path, scenario, play)
    assert not result.passed
    artifact = json.loads(result.scenarios[0].artifact_path.read_text(encoding="utf-8"))
    assert artifact["failing_turn_index"] == 1
    assert artifact["resolution_debug"]["history_resolution_skipped_reason"] == "topic_switch"
    assert "standalone_question" in artifact["error"]


async def test_script_longer_than_max_turns_fails_before_a_model_call(tmp_path):
    scenario = _two_turn_script(tmp_path, max_turns=1)

    async def play(user: str, *, scenario_id: str, turn_index: int) -> dict:
        raise AssertionError("max_turns must fail before the turn player is called")

    result = await _run(tmp_path, scenario, play)
    assert not result.passed
    artifact = json.loads(result.scenarios[0].artifact_path.read_text(encoding="utf-8"))
    assert artifact["failing_turn_index"] == 1
    assert artifact["user"] == scenario.turns[1].user
    assert artifact["assistant"] is None
    assert artifact["turns"] == []
    assert "max_turns" in artifact["error"]


async def test_failure_artifact_records_trace_and_config(tmp_path):
    scenario = _two_turn_script(tmp_path)
    play = _player(
        [
            _chat(
                "Captains receive 18 paid days off.",
                reason=None,
                applied=True,
                resolved="How many paid days off does policy POL-HR-014 grant captains?",
            ),
            _passing_responses()[1],
        ]
    )
    result = await _run(tmp_path, scenario, play)
    assert not result.passed
    assert play.calls == [scenario.turns[0].user]
    artifact = json.loads(result.scenarios[0].artifact_path.read_text(encoding="utf-8"))
    assert artifact["scenario_id"] == scenario.id
    assert artifact["failing_turn_index"] == 0
    assert artifact["user"] == scenario.turns[0].user
    assert artifact["assistant"] == "Captains receive 18 paid days off."
    assert artifact["resolution_debug"] == {
        "history_resolution_applied": True,
        "history_resolution_skipped_reason": None,
        "history_resolved_query": (
            "How many paid days off does policy POL-HR-014 grant captains?"
        ),
    }
    assert artifact["logical_keys"] == ["hr-pto-policy", "product-harbor-pass"]
    assert artifact["documents"] == [
        {"logical_key": "hr-pto-policy", "document_id": "doc-pto"},
        {"logical_key": "product-harbor-pass", "document_id": "doc-harbor"},
    ]
    assert artifact["provider"] == "mock-provider"
    assert artifact["model"] == "mock-model"
    assert artifact["persona"] == "default"
    assert artifact["retrieval_config"] == {"match_count": {"value": 5, "source": "env"}}
    assert artifact["chunk_settings"]["CHUNKING_STRATEGY"] == config.CHUNKING_STRATEGY
    assert artifact["turns"][0]["retrieval_debug"]["history_resolution_applied"] is True


async def test_contains_label_matches_the_resolved_query_case_insensitively(tmp_path):
    scenario = _write_script(
        tmp_path,
        [
            {
                "user": "Does it convert unused days to wages?",
                "resolution": {"contains": "pol-hr-014"},
                "expected_facts": ["do not convert to wages"],
            }
        ],
        max_turns=1,
        scenario_id="contains-label",
    )
    play = _player(
        [
            _chat(
                "Unused days do not convert to wages.",
                reason=None,
                applied=True,
                resolved="Does POL-HR-014 convert unused days to wages?",
            )
        ]
    )
    result = await _run(tmp_path, scenario, play)
    assert result.passed

    mismatch = _player(
        [
            _chat(
                "Unused days do not convert to wages.",
                reason=None,
                applied=True,
                resolved="Does the policy convert unused days to wages?",
            )
        ]
    )
    failed = await _run(tmp_path, scenario, mismatch)
    assert not failed.passed
    assert "pol-hr-014" in failed.scenarios[0].error


async def test_contains_label_accepts_an_applied_echo_of_the_user_line(tmp_path):
    user = (
        "And what is the dinner reimbursement limit when travel orders "
        "send a captain away from Saltmere overnight?"
    )
    scenario = _write_script(
        tmp_path,
        [
            {
                "user": user,
                "resolution": {"contains": "travel orders"},
                "expected_facts": ["40 USD"],
            }
        ],
        max_turns=1,
        scenario_id="echo-contains",
    )
    echoed = await _run(
        tmp_path,
        scenario,
        _player([_chat("The limit is 40 USD.", reason=None, applied=True, original=user)]),
    )
    assert echoed.passed

    dropped = await _run(
        tmp_path,
        scenario,
        _player(
            [
                _chat(
                    "The limit is 40 USD.",
                    reason=None,
                    applied=True,
                    original=user,
                    resolved="What is the dinner reimbursement limit?",
                )
            ]
        ),
    )
    assert not dropped.passed
    assert "travel orders" in dropped.scenarios[0].error

    missing = await _run(
        tmp_path,
        scenario,
        _player(
            [
                _chat(
                    "The limit is 40 USD.",
                    reason=None,
                    applied=True,
                    original="What is the dinner reimbursement limit overnight?",
                )
            ]
        ),
    )
    assert not missing.passed
    assert "travel orders" in missing.scenarios[0].error


async def test_refusal_label_uses_the_answer_phrase_rule(tmp_path):
    scenario = _write_script(
        tmp_path,
        [
            {
                "user": "What sabbatical stipend does policy POL-HR-014 pay?",
                "resolution": "empty_history",
                "expected_refusal": {
                    "phrases": ["Not enough information"],
                    "forbidden": ["sabbatical stipend is"],
                },
            }
        ],
        max_turns=1,
        scenario_id="refusal-label",
    )
    passed = await _run(
        tmp_path,
        scenario,
        _player([_chat("Not enough information.", reason="empty_history", applied=False)]),
    )
    assert passed.passed
    missing = await _run(
        tmp_path,
        scenario,
        _player(
            [
                _chat(
                    "The sabbatical stipend is 5000 USD.",
                    reason="empty_history",
                    applied=False,
                )
            ]
        ),
    )
    assert not missing.passed


async def test_runner_does_not_add_a_user_turn_when_the_assistant_asks(tmp_path):
    scenario = _write_script(
        tmp_path,
        [
            {
                "user": "How many paid days off does policy POL-HR-014 grant captains?",
                "resolution": "empty_history",
                "expected_facts": ["18 paid days off"],
            }
        ],
        max_turns=1,
        scenario_id="stops-at-script",
    )
    play = _player(
        [
            _chat(
                "Captains receive 18 paid days off. Which policy should I open next?",
                reason="empty_history",
                applied=False,
            )
        ]
    )
    result = await _run(tmp_path, scenario, play)
    assert result.passed
    assert play.calls == [scenario.turns[0].user]


async def test_chunk_setting_mismatch_fails_before_a_model_call(tmp_path):
    scenario = _two_turn_script(tmp_path)
    called = False

    async def play(user: str, *, scenario_id: str, turn_index: int) -> dict:
        nonlocal called
        called = True
        raise AssertionError("a chunk mismatch must not call the model")

    manifest = _manifest(("hr-pto-policy", "doc-pto"), ("product-harbor-pass", "doc-harbor"))
    manifest["chunk_settings"] = {**manifest["chunk_settings"], "CHUNK_SIZE": config.CHUNK_SIZE + 1}
    with pytest.raises(ConversationScenarioError, match="CHUNK_SIZE"):
        await run_conversation_scenarios(
            [scenario],
            manifest=manifest,
            tenant_id="eval-tenant",
            listed_document_ids=["doc-pto", "doc-harbor"],
            play_turn=play,
            artifact_dir=tmp_path / "artifacts",
            provider="mock-provider",
            configured_model="configured-model",
            persona="default",
            retrieval_config={},
        )
    assert called is False


async def test_unrelated_tenant_documents_fail_before_a_model_call(tmp_path):
    scenario = _two_turn_script(tmp_path)
    called = False

    async def play(user: str, *, scenario_id: str, turn_index: int) -> dict:
        nonlocal called
        called = True
        raise AssertionError("a dirty tenant must not be searched")

    manifest = _manifest(("hr-pto-policy", "doc-pto"), ("product-harbor-pass", "doc-harbor"))
    with pytest.raises(ConversationScenarioError, match="unrelated documents"):
        await run_conversation_scenarios(
            [scenario],
            manifest=manifest,
            tenant_id="eval-tenant",
            listed_document_ids=["doc-pto", "doc-harbor", "doc-other"],
            play_turn=play,
            artifact_dir=tmp_path / "artifacts",
            provider="mock-provider",
            configured_model="configured-model",
            persona="default",
            retrieval_config={},
        )
    assert called is False


def test_runner_does_not_call_the_single_query_session_helper():
    source = inspect.getsource(conversation_scenarios.run_conversation_scenarios)
    source += inspect.getsource(conversation_scenarios._run_scenario)
    source += inspect.getsource(CorpusChatPlayer.__call__)
    assert "simulate_session" not in source
    assert "retrieve_for_documents" not in source
    assert "routes" not in source
    assert "upload" not in source


def _manifest_file(tmp_path, doc_id: str = "doc-pto") -> tuple[dict, object]:
    payload = _manifest(("hr-pto-policy", doc_id))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload, path


def _script_dir(tmp_path, turns: list[dict], *, max_turns: int):
    directory = tmp_path / "scenarios"
    directory.mkdir()
    _write_script(
        directory,
        turns,
        max_turns=max_turns,
        scenario_id="cli-script",
        logical_keys=["hr-pto-policy"],
    )
    return directory


def _pto_turns() -> list[dict]:
    return [
        {
            "user": "How many paid days off does policy POL-HR-014 grant captains?",
            "resolution": "empty_history",
            "expected_facts": ["18 paid days off"],
        },
        {
            "user": "Do unused days convert to wages under policy POL-HR-014?",
            "resolution": "standalone_question",
            "expected_facts": ["do not convert to wages"],
        },
    ]


async def test_in_process_player_uses_chat_debug_and_one_session(tmp_path, monkeypatch):
    recorded = []

    async def create_session(session_id=None, tenant_id=None):
        recorded.append(("session", tenant_id))
        return SimpleNamespace(id="session-1")

    async def answer_question_for_document(question, doc_id, match_count=5, **kwargs):
        recorded.append(("chat", question, doc_id, match_count, kwargs))
        first_turn = sum(1 for row in recorded if row[0] == "chat") == 1
        if first_turn:
            return _chat(
                "Captains receive 18 paid days off.",
                reason="empty_history",
                applied=False,
            )
        return _chat(
            "Unused days do not convert to wages.",
            reason="standalone_question",
            applied=False,
        )

    monkeypatch.setattr("services.session_service.create_session", create_session)
    monkeypatch.setattr(
        "services.chat_service.answer_question_for_document",
        answer_question_for_document,
    )
    _manifest_payload, manifest_path = _manifest_file(tmp_path)
    directory = _script_dir(tmp_path, _pto_turns(), max_turns=2)
    result = await run_checked_in_conversations(
        directory,
        tenant_id="eval-tenant",
        manifest_path=manifest_path,
        artifact_dir=tmp_path / "artifacts",
        listed_document_ids=["doc-pto"],
    )
    assert result.passed
    assert recorded[0] == ("session", "eval-tenant")
    assert [row[0] for row in recorded].count("session") == 1
    questions = [row[1] for row in recorded if row[0] == "chat"]
    assert questions == [turn["user"] for turn in _pto_turns()]
    for row in recorded:
        if row[0] != "chat":
            continue
        assert row[2] == "doc-pto"
        assert row[4]["debug_retrieval"] is True
        assert row[4]["scope"] == "tenant"
        assert row[4]["session_id"] == "session-1"
        assert row[4]["auth"].tenant_id == "eval-tenant"


def test_command_exits_nonzero_before_the_model_when_the_script_is_too_long(
    tmp_path, monkeypatch, capsys
):
    _manifest_payload, manifest_path = _manifest_file(tmp_path)
    directory = _script_dir(tmp_path, _pto_turns(), max_turns=1)
    called = []

    async def listed(tenant_id):
        assert tenant_id == "eval-tenant"
        return ["doc-pto"]

    async def answer(*args, **kwargs):
        called.append(args)
        raise AssertionError("the model must not be called")

    monkeypatch.setattr("db.list_tenant_documents", listed)
    monkeypatch.setattr("services.chat_service.answer_question_for_document", answer)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backend.cli",
            "eval-conversations",
            "--scenarios",
            str(directory),
            "--tenant-id",
            "eval-tenant",
            "--manifest",
            str(manifest_path),
            "--export",
            str(tmp_path / "artifacts"),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1
    assert called == []
    assert "max_turns" in capsys.readouterr().out


def test_command_exits_nonzero_when_the_manifest_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backend.cli",
            "eval-conversations",
            "--scenarios",
            str(CHECKED_IN_SCENARIOS),
            "--tenant-id",
            "eval-tenant",
            "--manifest",
            str(tmp_path / "missing.json"),
            "--export",
            str(tmp_path / "artifacts"),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1
    assert "Could not read corpus manifest" in capsys.readouterr().err


async def test_command_reports_a_failed_scenario(tmp_path, monkeypatch):
    _manifest_payload, manifest_path = _manifest_file(tmp_path)
    directory = _script_dir(tmp_path, _pto_turns()[:1], max_turns=1)

    async def listed(tenant_id):
        return ["doc-pto"]

    async def create_session(session_id=None, tenant_id=None):
        return SimpleNamespace(id="session-1")

    async def answer(*args, **kwargs):
        return _chat("No fact here.", reason="empty_history", applied=False)

    monkeypatch.setattr("db.list_tenant_documents", listed)
    monkeypatch.setattr("services.session_service.create_session", create_session)
    monkeypatch.setattr("services.chat_service.answer_question_for_document", answer)
    with pytest.raises(ConversationScenarioError, match="1 scenario"):
        await cmd_eval_conversations(
            str(directory),
            "eval-tenant",
            str(manifest_path),
            str(tmp_path / "artifacts"),
        )

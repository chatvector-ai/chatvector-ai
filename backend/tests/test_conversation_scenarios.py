"""Fixed conversation scripts stay a list of user lines."""

import json

import pytest

from services.conversation_scenarios import (
    SCENARIO_CLASSES,
    CHECKED_IN_SCENARIOS,
    ConversationScenarioError,
    load_scenario,
    load_scenario_directory,
)


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

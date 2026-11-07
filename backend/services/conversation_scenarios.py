"""Fixed multi-turn scripts for the evaluation corpus.

Each scenario file is the whole conversation. The loader reads those user
lines and does not add any. This module does not call ``simulate_session``
and does not score recall or nDCG.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SCENARIO_CLASSES = frozenset(
    {
        "pronoun",
        "demonstrative",
        "ordinal",
        "correction",
        "topic_switch",
        "return_to_earlier_subject",
        "multi_document_continuation",
        "ambiguity",
        "absent_answer",
        "contradictory_sources",
        "long_session",
    }
)
SKIP_REASONS = frozenset(
    {
        "empty_history",
        "standalone_question",
        "topic_switch",
        "disabled",
        "compare_skip",
    }
)
_SCENARIO_FIELDS = frozenset({"id", "class", "max_turns", "logical_keys", "turns"})
_TURN_FIELDS = frozenset({"user", "resolution", "expected_facts", "expected_refusal"})
_FACT_FIELDS = frozenset({"text", "alternates"})
_REFUSAL_FIELDS = frozenset({"phrases", "forbidden"})
_RESOLUTION_FIELDS = frozenset({"contains"})

CHECKED_IN_SCENARIOS = (
    Path(__file__).resolve().parents[1] / "eval" / "brinewick" / "scenarios"
)


class ConversationScenarioError(ValueError):
    """A scenario file cannot be loaded."""


@dataclass(frozen=True)
class ExpectedFact:
    """One labeled fact. Alternates are the only other accepted phrasings."""

    text: str
    alternates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedRefusal:
    """A labeled refusal phrase, plus strings the answer must not contain."""

    phrases: tuple[str, ...]
    forbidden: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolutionContains:
    """Resolution ran, and the changed query still contains this text."""

    text: str


@dataclass(frozen=True)
class ConversationTurn:
    """One fixed user line and the checks that line requires."""

    user: str
    resolution: str | ResolutionContains | None = None
    expected_facts: tuple[ExpectedFact, ...] = ()
    expected_refusal: ExpectedRefusal | None = None


@dataclass(frozen=True)
class ConversationScenario:
    """A script played in order against the eval corpus."""

    id: str
    scenario_class: str
    max_turns: int
    logical_keys: tuple[str, ...]
    turns: tuple[ConversationTurn, ...]
    source_path: Path | None = None


def load_scenario_directory(path: str | Path) -> list[ConversationScenario]:
    """Load every ``*.json`` script in ``path``, in file-name order."""
    directory = Path(path)
    if not directory.is_dir():
        raise ConversationScenarioError(f"Scenario directory {directory} does not exist")
    files = sorted(item for item in directory.glob("*.json") if item.is_file())
    if not files:
        raise ConversationScenarioError(f"Scenario directory {directory} has no scripts")
    scenarios = [load_scenario(item) for item in files]
    seen: set[str] = set()
    for scenario in scenarios:
        if scenario.id in seen:
            raise ConversationScenarioError(f"Duplicate scenario id {scenario.id!r}")
        seen.add(scenario.id)
    return scenarios


def load_scenario(path: str | Path) -> ConversationScenario:
    """Load one script. User lines are copied from the file unchanged."""
    source = Path(path)
    try:
        raw_text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConversationScenarioError(f"Could not read scenario {source}: {exc}") from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConversationScenarioError(f"Could not read scenario {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConversationScenarioError(f"Scenario {source} must be a JSON object")
    unknown = set(raw) - _SCENARIO_FIELDS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConversationScenarioError(f"Scenario {source} has unknown fields: {names}")
    missing = _SCENARIO_FIELDS - set(raw)
    if missing:
        names = ", ".join(sorted(missing))
        raise ConversationScenarioError(f"Scenario {source} is missing {names}")

    scenario_id = _require_token(raw["id"], f"Scenario {source} id")
    scenario_class = raw["class"]
    if scenario_class not in SCENARIO_CLASSES:
        raise ConversationScenarioError(
            f"Scenario {scenario_id!r} has unknown class {scenario_class!r}"
        )
    max_turns = raw["max_turns"]
    if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns < 1:
        raise ConversationScenarioError(
            f"Scenario {scenario_id!r} max_turns must be an integer of at least 1"
        )
    logical_keys = _logical_keys(raw["logical_keys"], scenario_id)
    turns_raw = raw["turns"]
    if not isinstance(turns_raw, list) or not turns_raw:
        raise ConversationScenarioError(f"Scenario {scenario_id!r} needs at least one turn")
    turns = tuple(
        _turn(item, scenario_id, index) for index, item in enumerate(turns_raw)
    )
    return ConversationScenario(
        id=scenario_id,
        scenario_class=scenario_class,
        max_turns=max_turns,
        logical_keys=logical_keys,
        turns=turns,
        source_path=source,
    )


def _turn(raw: object, scenario_id: str, index: int) -> ConversationTurn:
    where = f"Scenario {scenario_id!r} turn {index}"
    if not isinstance(raw, dict):
        raise ConversationScenarioError(f"{where} must be a JSON object")
    unknown = set(raw) - _TURN_FIELDS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConversationScenarioError(f"{where} has unknown fields: {names}")
    if "user" not in raw:
        raise ConversationScenarioError(f"{where} is missing user")
    user = raw["user"]
    if not isinstance(user, str) or user == "" or user.strip() != user:
        raise ConversationScenarioError(f"{where} user must be a non-empty string")
    resolution = _resolution(raw.get("resolution", None), where)
    facts = _expected_facts(raw, where)
    refusal = _expected_refusal(raw, where)
    return ConversationTurn(
        user=user,
        resolution=resolution,
        expected_facts=tuple(facts),
        expected_refusal=refusal,
    )


def _resolution(value: object, where: str) -> str | ResolutionContains | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value not in SKIP_REASONS:
            raise ConversationScenarioError(f"{where} has unknown resolution label {value!r}")
        return value
    if not isinstance(value, dict):
        raise ConversationScenarioError(f"{where} resolution must be a label or an object")
    unknown = set(value) - _RESOLUTION_FIELDS
    if unknown or "contains" not in value:
        names = ", ".join(sorted(unknown)) or "contains"
        raise ConversationScenarioError(f"{where} has invalid resolution fields: {names}")
    text = value["contains"]
    if not isinstance(text, str) or not text.strip() or text.strip() != text:
        raise ConversationScenarioError(f"{where} resolution contains must be a non-empty string")
    return ResolutionContains(text=text)


def _expected_facts(raw: dict, where: str) -> list[ExpectedFact]:
    if "expected_facts" not in raw or raw["expected_facts"] is None:
        return []
    value = raw["expected_facts"]
    if not isinstance(value, list) or not value:
        raise ConversationScenarioError(f"{where} has invalid expected_facts")
    facts: list[ExpectedFact] = []
    for item in value:
        if isinstance(item, str):
            facts.append(ExpectedFact(text=_label_text(item, where, "expected_facts")))
            continue
        if not isinstance(item, dict):
            raise ConversationScenarioError(f"{where} has invalid expected_facts")
        unknown = set(item) - _FACT_FIELDS
        if unknown or "text" not in item:
            names = ", ".join(sorted(unknown)) or "text"
            raise ConversationScenarioError(
                f"{where} has invalid expected_facts fields: {names}"
            )
        alternates = item.get("alternates", [])
        if not isinstance(alternates, list) or any(
            not isinstance(alternate, str) or not alternate.strip() for alternate in alternates
        ):
            raise ConversationScenarioError(f"{where} has invalid expected_facts")
        facts.append(
            ExpectedFact(
                text=_label_text(item["text"], where, "expected_facts"),
                alternates=tuple(alternates),
            )
        )
    return facts


def _expected_refusal(raw: dict, where: str) -> ExpectedRefusal | None:
    if "expected_refusal" not in raw or raw["expected_refusal"] is None:
        return None
    value = raw["expected_refusal"]
    if not isinstance(value, dict):
        raise ConversationScenarioError(f"{where} has invalid expected_refusal")
    unknown = set(value) - _REFUSAL_FIELDS
    if unknown or "phrases" not in value:
        names = ", ".join(sorted(unknown)) or "phrases"
        raise ConversationScenarioError(
            f"{where} has invalid expected_refusal fields: {names}"
        )
    forbidden = value.get("forbidden", [])
    if not isinstance(forbidden, list) or any(
        not isinstance(item, str) or not item.strip() for item in forbidden
    ):
        raise ConversationScenarioError(f"{where} has invalid expected_refusal")
    phrases = value["phrases"]
    if not isinstance(phrases, list) or not phrases:
        raise ConversationScenarioError(f"{where} has invalid expected_refusal")
    return ExpectedRefusal(
        phrases=tuple(_label_text(item, where, "expected_refusal") for item in phrases),
        forbidden=tuple(forbidden),
    )


def _logical_keys(value: object, scenario_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConversationScenarioError(
            f"Scenario {scenario_id!r} logical_keys must list at least one key"
        )
    keys: list[str] = []
    seen: set[str] = set()
    for item in value:
        key = _require_token(item, f"Scenario {scenario_id!r} logical_key")
        if key in seen:
            raise ConversationScenarioError(
                f"Scenario {scenario_id!r} repeats logical_key {key!r}"
            )
        seen.add(key)
        keys.append(key)
    return tuple(keys)


def _require_token(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ConversationScenarioError(f"{label} must be a non-empty string")
    if any(char.isspace() or char == "\x00" or char in "/\\" for char in value):
        raise ConversationScenarioError(f"{label} {value!r} is not a stable token")
    return value


def _label_text(value: object, where: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConversationScenarioError(f"{where} has invalid {field_name}")
    return value.strip()

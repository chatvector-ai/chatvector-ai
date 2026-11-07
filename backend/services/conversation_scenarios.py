"""Fixed multi-turn scripts for the evaluation corpus.

Each scenario file is the whole conversation. The loader copies those user
lines. The runner sends each line in order, checks the turn's resolution
label and expected fact or refusal, and writes a trace. It stops at the
last scripted line. A script longer than ``max_turns`` fails before the
turn player is called.

This runner is separate from single-query evaluation. It does not score
recall or nDCG.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from core.config import config

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
# Same default match_count as in-process chat. Tenant scope searches the corpus.
CONVERSATION_MATCH_COUNT = 5


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


@dataclass(frozen=True)
class ScenarioRunRecord:
    """One scenario's pass/fail and the artifact that records it."""

    scenario_id: str
    passed: bool
    artifact_path: Path
    error: str | None = None


@dataclass
class ConversationRunResult:
    """The scripts played in one harness run."""

    scenarios: list[ScenarioRunRecord] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(record.passed for record in self.scenarios)


def load_corpus_manifest(path: str | Path) -> dict:
    """Read a corpus manifest. Logical keys stay the stable document identity."""
    source = Path(path)
    try:
        raw_text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConversationScenarioError(f"Could not read corpus manifest {source}: {exc}") from exc
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConversationScenarioError(f"Could not read corpus manifest {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConversationScenarioError(f"Corpus manifest {source} must be a JSON object")
    _document_index(raw)
    settings = raw.get("chunk_settings")
    if not isinstance(settings, dict):
        raise ConversationScenarioError(f"Corpus manifest {source} is missing chunk_settings")
    for name in ("CHUNK_SIZE", "CHUNK_OVERLAP", "CHUNKING_STRATEGY"):
        if name not in settings:
            raise ConversationScenarioError(f"Corpus manifest {source} is missing {name}")
    if "tenant_id" not in raw or not isinstance(raw["tenant_id"], str) or not raw["tenant_id"]:
        raise ConversationScenarioError(f"Corpus manifest {source} is missing tenant_id")
    return raw


def assert_corpus_ready(manifest: dict, tenant_id: str, listed_document_ids: list[str]) -> None:
    """Refuse a run whose tenant is not exactly the loaded corpus.

    Chunk settings are compared to the process before any turn is sent.
    Extra tenant documents are unrelated to the corpus and are not searched.
    """
    manifest_tenant = manifest.get("tenant_id")
    if manifest_tenant != tenant_id:
        raise ConversationScenarioError(
            f"Manifest tenant {manifest_tenant!r} does not match {tenant_id!r}"
        )
    settings = manifest["chunk_settings"]
    mismatches: list[str] = []
    if settings["CHUNK_SIZE"] != config.CHUNK_SIZE:
        mismatches.append(
            f"CHUNK_SIZE corpus {settings['CHUNK_SIZE']}, process {config.CHUNK_SIZE}"
        )
    if settings["CHUNK_OVERLAP"] != config.CHUNK_OVERLAP:
        mismatches.append(
            "CHUNK_OVERLAP corpus "
            f"{settings['CHUNK_OVERLAP']}, process {config.CHUNK_OVERLAP}"
        )
    declared = str(settings["CHUNKING_STRATEGY"]).strip().lower()
    process = config.CHUNKING_STRATEGY.strip().lower()
    if declared != process:
        mismatches.append(
            f"CHUNKING_STRATEGY corpus {settings['CHUNKING_STRATEGY']!r}, "
            f"process {config.CHUNKING_STRATEGY!r}"
        )
    if mismatches:
        raise ConversationScenarioError("; ".join(mismatches))

    manifest_ids = {row["document_id"] for row in manifest["documents"]}
    listed = set(listed_document_ids)
    if listed == manifest_ids:
        return
    extra = sorted(listed - manifest_ids)
    missing = sorted(manifest_ids - listed)
    parts = ["Tenant document list does not match the corpus manifest"]
    if extra:
        parts.append(f"unrelated documents: {extra}")
    if missing:
        parts.append(f"missing documents: {missing}")
    raise ConversationScenarioError("; ".join(parts))


async def run_conversation_scenarios(
    scenarios: list[ConversationScenario],
    *,
    manifest: dict,
    tenant_id: str,
    listed_document_ids: list[str],
    play_turn,
    artifact_dir: str | Path,
    provider: str,
    configured_model: str | None,
    persona: str,
    retrieval_config: dict,
) -> ConversationRunResult:
    """Play each script in order and write one artifact per scenario.

    ``play_turn`` receives only the user text stored on the turn. The runner
    does not append a line when the assistant asks a question, and it does
    not call ``play_turn`` when the script is longer than ``max_turns``.
    """
    assert_corpus_ready(manifest, tenant_id, listed_document_ids)
    documents = _document_index(manifest)
    directory = Path(artifact_dir)
    directory.mkdir(parents=True, exist_ok=True)
    result = ConversationRunResult()
    for scenario in scenarios:
        record = await _run_scenario(
            scenario,
            documents=documents,
            play_turn=play_turn,
            artifact_dir=directory,
            provider=provider,
            configured_model=configured_model,
            persona=persona,
            retrieval_config=retrieval_config,
            chunk_settings=dict(manifest["chunk_settings"]),
        )
        result.scenarios.append(record)
    return result


async def _run_scenario(
    scenario: ConversationScenario,
    *,
    documents: dict[str, str],
    play_turn,
    artifact_dir: Path,
    provider: str,
    configured_model: str | None,
    persona: str,
    retrieval_config: dict,
    chunk_settings: dict,
) -> ScenarioRunRecord:
    missing = [key for key in scenario.logical_keys if key not in documents]
    if missing:
        error = f"Scenario {scenario.id!r} names unknown logical keys: {missing}"
        path = _write_artifact(
            artifact_dir,
            _artifact_payload(
                scenario,
                status="failed",
                failing_turn_index=0,
                user=scenario.turns[0].user,
                assistant=None,
                resolution_debug=_empty_resolution_debug(),
                turns=[],
                error=error,
                provider=provider,
                model=configured_model,
                persona=persona,
                retrieval_config=retrieval_config,
                chunk_settings=chunk_settings,
                documents=documents,
            ),
        )
        return ScenarioRunRecord(scenario.id, False, path, error)

    if len(scenario.turns) > scenario.max_turns:
        index = scenario.max_turns
        error = (
            f"Scenario {scenario.id!r} has {len(scenario.turns)} user turns "
            f"and max_turns is {scenario.max_turns}"
        )
        path = _write_artifact(
            artifact_dir,
            _artifact_payload(
                scenario,
                status="failed",
                failing_turn_index=index,
                user=scenario.turns[index].user,
                assistant=None,
                resolution_debug=_empty_resolution_debug(),
                turns=[],
                error=error,
                provider=provider,
                model=configured_model,
                persona=persona,
                retrieval_config=retrieval_config,
                chunk_settings=chunk_settings,
                documents=documents,
            ),
        )
        return ScenarioRunRecord(scenario.id, False, path, error)

    played: list[dict] = []
    for index, turn in enumerate(scenario.turns):
        response = await play_turn(turn.user, scenario_id=scenario.id, turn_index=index)
        observation = _observe_turn(turn, index, response)
        played.append(observation)
        if observation["failures"]:
            error = "; ".join(observation["failures"])
            path = _write_artifact(
                artifact_dir,
                _artifact_payload(
                    scenario,
                    status="failed",
                    failing_turn_index=index,
                    user=turn.user,
                    assistant=observation["assistant"],
                    resolution_debug=observation["resolution_debug"],
                    turns=played,
                    error=error,
                    provider=provider,
                    model=observation["model"] or configured_model,
                    persona=persona,
                    retrieval_config=observation["retrieval_config"] or retrieval_config,
                    chunk_settings=chunk_settings,
                    documents=documents,
                ),
            )
            return ScenarioRunRecord(scenario.id, False, path, error)

    last = played[-1]
    path = _write_artifact(
        artifact_dir,
        _artifact_payload(
            scenario,
            status="passed",
            failing_turn_index=None,
            user=None,
            assistant=None,
            resolution_debug=None,
            turns=played,
            error=None,
            provider=provider,
            model=last["model"] or configured_model,
            persona=persona,
            retrieval_config=last["retrieval_config"] or retrieval_config,
            chunk_settings=chunk_settings,
            documents=documents,
        ),
    )
    return ScenarioRunRecord(scenario.id, True, path, None)


def _observe_turn(turn: ConversationTurn, index: int, response: object) -> dict:
    if not isinstance(response, dict):
        return {
            "index": index,
            "user": turn.user,
            "assistant": None,
            "model": None,
            "resolution_debug": _empty_resolution_debug(),
            "retrieval_config": None,
            "retrieval_debug": None,
            "failures": ["chat response must be an object"],
        }
    assistant = response.get("answer")
    if assistant is not None and not isinstance(assistant, str):
        assistant = str(assistant)
    model = response.get("model")
    if model is not None and not isinstance(model, str):
        model = str(model)
    retrieval_debug = response.get("retrieval_debug")
    if not isinstance(retrieval_debug, dict):
        retrieval_debug = {}
    resolution_debug = _resolution_debug(retrieval_debug)
    effective = retrieval_debug.get("effective_config")
    retrieval_config = effective if isinstance(effective, dict) else None
    failures: list[str] = []
    if response.get("status") != "ok":
        failures.append(f"chat status {response.get('status')!r}")
    failures.extend(_resolution_failures(turn, retrieval_debug))
    answer_text = assistant or ""
    failures.extend(_fact_failures(turn, answer_text))
    failures.extend(_refusal_failures(turn, answer_text))
    return {
        "index": index,
        "user": turn.user,
        "assistant": assistant,
        "model": model,
        "resolution_debug": resolution_debug,
        "retrieval_config": retrieval_config,
        "retrieval_debug": retrieval_debug,
        "failures": failures,
    }


def _resolution_failures(turn: ConversationTurn, debug: dict) -> list[str]:
    label = turn.resolution
    if label is None:
        return []
    applied = debug.get("history_resolution_applied")
    if isinstance(label, str):
        reason = debug.get("history_resolution_skipped_reason")
        if applied is not False or reason != label:
            return [
                f"resolution label {label!r} does not match "
                f"applied={applied!r} skipped_reason={reason!r}"
            ]
        return []
    resolved = debug.get("history_resolved_query")
    if (
        applied is not True
        or not isinstance(resolved, str)
        or not _contains_label(resolved, label.text)
    ):
        shown = resolved if isinstance(resolved, str) else None
        return [
            f"resolution label containing {label.text!r} does not match "
            f"applied={applied!r} history_resolved_query={shown!r}"
        ]
    return []


def _fact_failures(turn: ConversationTurn, answer: str) -> list[str]:
    missing = [fact.text for fact in turn.expected_facts if not _fact_in_text(fact, answer)]
    if not missing:
        return []
    return [f"answer is missing expected facts: {missing}"]


def _refusal_failures(turn: ConversationTurn, answer: str) -> list[str]:
    refusal = turn.expected_refusal
    if refusal is None:
        return []
    has_phrase = any(_contains_label(answer, phrase) for phrase in refusal.phrases)
    forbidden = [item for item in refusal.forbidden if _contains_label(answer, item)]
    if has_phrase and not forbidden:
        return []
    return [
        "answer does not match the labeled refusal "
        f"(phrase={has_phrase}, forbidden={forbidden})"
    ]


def _fact_in_text(fact: ExpectedFact, text: str) -> bool:
    """Same case-insensitive substring rule as the answer labels."""
    if _contains_label(text, fact.text):
        return True
    return any(_contains_label(text, alternate) for alternate in fact.alternates)


def _contains_label(text: str, label: str) -> bool:
    return label.casefold() in text.casefold()


def _resolution_debug(retrieval_debug: dict) -> dict:
    return {
        "history_resolution_applied": retrieval_debug.get("history_resolution_applied"),
        "history_resolution_skipped_reason": retrieval_debug.get(
            "history_resolution_skipped_reason"
        ),
        "history_resolved_query": retrieval_debug.get("history_resolved_query"),
    }


def _empty_resolution_debug() -> dict:
    return {
        "history_resolution_applied": None,
        "history_resolution_skipped_reason": None,
        "history_resolved_query": None,
    }


def _artifact_payload(
    scenario: ConversationScenario,
    *,
    status: str,
    failing_turn_index: int | None,
    user: str | None,
    assistant: str | None,
    resolution_debug: dict | None,
    turns: list[dict],
    error: str | None,
    provider: str,
    model: str | None,
    persona: str,
    retrieval_config: dict,
    chunk_settings: dict,
    documents: dict[str, str],
) -> dict:
    return {
        "scenario_id": scenario.id,
        "scenario_class": scenario.scenario_class,
        "status": status,
        "failing_turn_index": failing_turn_index,
        "user": user,
        "assistant": assistant,
        "resolution_debug": resolution_debug,
        "logical_keys": list(scenario.logical_keys),
        "documents": [
            {"logical_key": key, "document_id": documents[key]}
            for key in scenario.logical_keys
            if key in documents
        ],
        "provider": provider,
        "model": model,
        "persona": persona,
        "retrieval_config": retrieval_config,
        "chunk_settings": chunk_settings,
        "turns": [
            {
                "index": turn["index"],
                "user": turn["user"],
                "assistant": turn["assistant"],
                "model": turn["model"],
                "resolution_debug": turn["resolution_debug"],
                "retrieval_debug": turn["retrieval_debug"],
                "failures": list(turn["failures"]),
            }
            for turn in turns
        ],
        "error": error,
    }


def _write_artifact(artifact_dir: Path, payload: dict) -> Path:
    path = artifact_dir / f"{payload['scenario_id']}.json"
    if path.parent.resolve() != artifact_dir.resolve():
        raise ConversationScenarioError(f"Artifact path {path} escapes {artifact_dir}")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def conversation_retrieval_config() -> dict:
    """Retrieval config the in-process chat path uses for one harness turn."""
    from services.chat_service import resolve_effective_retrieval

    effective = resolve_effective_retrieval(
        match_count=CONVERSATION_MATCH_COUNT,
        scope="tenant",
        retrieval_fields=None,
    )
    return effective.to_debug_dict()


class CorpusChatPlayer:
    """Send one fixed user line through in-process chat.

    History accumulates on a session created for the scenario. The public
    chat route is not called, so the chat rate limit does not apply.
    """

    def __init__(self, *, tenant_id: str, anchor_document_id: str) -> None:
        self.tenant_id = tenant_id
        self.anchor_document_id = anchor_document_id
        self._session_ids: dict[str, str] = {}

    async def __call__(self, user: str, *, scenario_id: str, turn_index: int) -> dict:
        from core.auth import AuthContext
        from services import chat_service, session_service

        if scenario_id not in self._session_ids:
            session = await session_service.create_session(tenant_id=self.tenant_id)
            self._session_ids[scenario_id] = session.id
        return await chat_service.answer_question_for_document(
            user,
            self.anchor_document_id,
            match_count=CONVERSATION_MATCH_COUNT,
            auth=AuthContext(tenant_id=self.tenant_id),
            session_id=self._session_ids[scenario_id],
            scope="tenant",
            debug_retrieval=True,
        )


async def run_checked_in_conversations(
    scenarios_dir: str | Path,
    *,
    tenant_id: str,
    manifest_path: str | Path,
    artifact_dir: str | Path,
    play_turn=None,
    listed_document_ids: list[str] | None = None,
) -> ConversationRunResult:
    """Load scripts and the corpus manifest, then play the scripts.

    When ``play_turn`` is omitted, each line goes through in-process chat.
    ``listed_document_ids`` defaults to the documents stored for ``tenant_id``.
    """
    manifest = load_corpus_manifest(manifest_path)
    scenarios = load_scenario_directory(scenarios_dir)
    if listed_document_ids is None:
        import db

        listed_document_ids = await db.list_tenant_documents(tenant_id)
    if play_turn is None:
        play_turn = CorpusChatPlayer(
            tenant_id=tenant_id,
            anchor_document_id=manifest["documents"][0]["document_id"],
        )
    return await run_conversation_scenarios(
        scenarios,
        manifest=manifest,
        tenant_id=tenant_id,
        listed_document_ids=list(listed_document_ids),
        play_turn=play_turn,
        artifact_dir=artifact_dir,
        provider=config.LLM_PROVIDER,
        configured_model=config.LLM_MODEL,
        persona=config.PROMPT_PERSONA,
        retrieval_config=conversation_retrieval_config(),
    )


def _document_index(manifest: dict) -> dict[str, str]:
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ConversationScenarioError("Corpus manifest needs at least one document")
    index: dict[str, str] = {}
    seen_ids: set[str] = set()
    for row in documents:
        if not isinstance(row, dict):
            raise ConversationScenarioError("Corpus manifest document must be an object")
        key = row.get("logical_key")
        doc_id = row.get("document_id")
        if not isinstance(key, str) or not key or not isinstance(doc_id, str) or not doc_id:
            raise ConversationScenarioError(
                "Corpus manifest document needs logical_key and document_id"
            )
        if key in index:
            raise ConversationScenarioError(f"Duplicate logical_key {key!r} in corpus manifest")
        if doc_id in seen_ids:
            raise ConversationScenarioError(
                f"Duplicate document_id {doc_id!r} in corpus manifest"
            )
        index[key] = doc_id
        seen_ids.add(doc_id)
    return index

"""Repository-local issue-pipeline settings. Loaded from the primary checkout root."""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_RELATIVE = Path("config/issue-pipeline.json")


def load_pipeline_config(repo_root: Path | None) -> dict | None:
    """Load the full repository issue-pipeline JSON from the primary checkout root."""

    if repo_root is None:
        return None
    path = Path(repo_root) / CONFIG_RELATIVE
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _unique_nonempty(names: list[str]) -> list[str] | None:
    seen: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        if name in seen:
            continue
        seen.append(name)
    return seen or None


def parse_required_checks_env(value: str | None) -> list[str] | None:
    if not value or not value.strip():
        return None
    return _unique_nonempty([part for part in value.split(",")])


def parse_required_checks_json(payload) -> list[str] | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("required_checks")
    if not isinstance(raw, list):
        return None
    if not raw:
        return None
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            return None
    return _unique_nonempty(raw)


def load_required_checks_from_config(repo_root: Path) -> list[str] | None:
    """Read `config/issue-pipeline.json` under the primary repository root."""

    path = Path(repo_root) / CONFIG_RELATIVE
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parse_required_checks_json(payload)


def resolve_required_checks(
    *,
    rules_payload,
    protection_payload,
    repo_root: Path | None,
) -> list[str] | None:
    """Env override, then GitHub rules, then branch protection, then repo config."""

    from .github import parse_protection_checks, parse_rules_required_checks

    from_env = parse_required_checks_env(os.environ.get("PIPELINE_REQUIRED_CHECKS"))
    if from_env is not None:
        return from_env

    if rules_payload is not None:
        parsed = parse_rules_required_checks(rules_payload)
        if parsed:
            return parsed

    if isinstance(protection_payload, dict):
        parsed = parse_protection_checks(protection_payload)
        if parsed:
            return parsed

    if repo_root is not None:
        from_file = load_required_checks_from_config(repo_root)
        if from_file is not None:
            return from_file

    return None

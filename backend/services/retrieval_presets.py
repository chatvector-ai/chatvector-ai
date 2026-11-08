"""Process-local named retrieval configuration presets.

Presets are loaded once at startup from ``RETRIEVAL_PRESETS_PATH`` and/or
``RETRIEVAL_PRESETS`` JSON. They are not tenant-scoped and are not mutated at
runtime.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from services.retrieval_config import (
    InvalidRetrievalConfigError,
    _OVERRIDE_FIELDS,
    resolve_retrieval_config,
)

logger = logging.getLogger(__name__)

_PRESET_OVERRIDE_FIELDS = frozenset(_OVERRIDE_FIELDS)

_loaded_presets: dict[str, dict[str, Any]] | None = None


class RetrievalPresetsLoadError(RuntimeError):
    """Raised when preset configuration cannot be loaded at process startup."""


class RetrievalPresetNotFoundError(LookupError):
    """Raised when a request references an unknown preset name."""

    def __init__(self, preset: str) -> None:
        self.preset = preset
        super().__init__(f"Unknown retrieval preset {preset!r}.")


def _normalize_preset_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        raise RetrievalPresetsLoadError("Preset names must be non-empty strings.")
    return normalized


def _validate_preset_body(name: str, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise RetrievalPresetsLoadError(
            f"Preset {name!r} must be a JSON object of retrieval override fields."
        )
    unknown = sorted(key for key in body if key not in _PRESET_OVERRIDE_FIELDS)
    if unknown:
        allowed = ", ".join(sorted(_PRESET_OVERRIDE_FIELDS))
        raise RetrievalPresetsLoadError(
            f"Preset {name!r} contains unknown field(s): {', '.join(unknown)}. "
            f"Allowed keys: {allowed}."
        )
    cleaned = {key: body[key] for key in body if body[key] is not None}
    try:
        resolve_retrieval_config(cleaned)
    except InvalidRetrievalConfigError as exc:
        raise RetrievalPresetsLoadError(f"Preset {name!r} has invalid values: {exc}") from exc
    return cleaned


def _parse_presets_document(raw: Any, *, source: str) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        raise RetrievalPresetsLoadError(
            f"{source} must be a JSON object mapping preset names to override objects."
        )
    parsed: dict[str, dict[str, Any]] = {}
    for raw_name, raw_body in raw.items():
        name = _normalize_preset_name(raw_name)
        if name in parsed:
            raise RetrievalPresetsLoadError(f"Duplicate preset name {name!r} in {source}.")
        parsed[name] = _validate_preset_body(name, raw_body)
    return parsed


def _read_presets_file(path: Path) -> dict[str, dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RetrievalPresetsLoadError(
            f"Failed to read RETRIEVAL_PRESETS_PATH={path!s}: {exc}"
        ) from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RetrievalPresetsLoadError(
            f"Invalid JSON in RETRIEVAL_PRESETS_PATH={path!s}: {exc.msg} at line {exc.lineno}."
        ) from exc
    return _parse_presets_document(raw, source=f"file {path}")


def _read_presets_env(raw_json: str) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RetrievalPresetsLoadError(
            f"Invalid JSON in RETRIEVAL_PRESETS env var: {exc.msg} at line {exc.lineno}."
        ) from exc
    return _parse_presets_document(raw, source="RETRIEVAL_PRESETS")


def load_retrieval_presets_from_settings(
    *,
    presets_path: str | None,
    presets_json: str | None,
) -> dict[str, dict[str, Any]]:
    """Load and merge preset maps. File entries are applied before env JSON."""
    merged: dict[str, dict[str, Any]] = {}
    if presets_path:
        path = Path(presets_path).expanduser()
        if not path.is_file():
            raise RetrievalPresetsLoadError(
                f"RETRIEVAL_PRESETS_PATH={path!s} is not a readable file."
            )
        merged.update(_read_presets_file(path))
    if presets_json:
        merged.update(_read_presets_env(presets_json))
    return merged


def load_retrieval_presets() -> dict[str, dict[str, Any]]:
    """Load presets from process configuration and cache them for requests."""
    global _loaded_presets
    from core.config import config

    _loaded_presets = load_retrieval_presets_from_settings(
        presets_path=config.RETRIEVAL_PRESETS_PATH,
        presets_json=config.RETRIEVAL_PRESETS,
    )
    if _loaded_presets:
        logger.info(
            "Loaded %d retrieval preset(s): %s",
            len(_loaded_presets),
            ", ".join(sorted(_loaded_presets)),
        )
    return dict(_loaded_presets)


def get_retrieval_presets() -> Mapping[str, Mapping[str, Any]]:
    if _loaded_presets is None:
        return load_retrieval_presets()
    return _loaded_presets


def list_configured_reranker_providers() -> list[str]:
    """Return reranker identifiers available in this process (no secrets)."""
    from core.config import config

    providers = ["similarity"]
    if config.COHERE_API_KEY:
        providers.append("cohere")
    return providers


def build_retrieval_preset_discovery() -> dict[str, list[str]]:
    """Names of loaded presets and configured reranker identifiers (no bodies)."""
    return {
        "preset_names": sorted(get_retrieval_presets().keys()),
        "reranker_providers": list_configured_reranker_providers(),
    }


def lookup_retrieval_preset(name: str) -> dict[str, Any]:
    preset_name = _normalize_preset_name(name)
    presets = get_retrieval_presets()
    body = presets.get(preset_name)
    if body is None:
        raise RetrievalPresetNotFoundError(preset_name)
    return dict(body)


def extract_preset_name(request_fields: Mapping[str, Any] | None) -> str | None:
    if not request_fields:
        return None
    top_preset = request_fields.get("preset")
    nested = request_fields.get("retrieval") or {}
    nested_preset = nested.get("preset") if isinstance(nested, Mapping) else None
    if top_preset is not None:
        return str(top_preset).strip() or None
    if nested_preset is not None:
        return str(nested_preset).strip() or None
    return None


def reset_retrieval_presets_for_tests() -> None:
    global _loaded_presets
    _loaded_presets = None


def set_retrieval_presets_for_tests(presets: Mapping[str, Mapping[str, Any]]) -> None:
    global _loaded_presets
    _loaded_presets = {
        _normalize_preset_name(name): _validate_preset_body(name, body)
        for name, body in presets.items()
    }

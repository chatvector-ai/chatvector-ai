"""Repository defaults, queue overrides, and standard-speed model policy."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import GraphError
from .pipeline_config import load_pipeline_config

# Task slugs the pipeline may request (standard speed only — no Fast variants).
STANDARD_VERIFIED_SLUGS = frozenset(
    {
        "composer-2.5",
        "grok-4.7-high",
        "claude-4.5-opus-high-thinking",
        "claude-sonnet-5-5-high",
        "gpt-5.6-sol-medium",
    }
)

# Legacy / explicit opt-in slugs that imply Fast mode — never auto-selected.
FAST_ONLY_SLUGS = frozenset(
    {
        "composer-2.5-fast",
        "cursor-grok-4.6-high-fast",
    }
)

SLUG_ALIASES = {
    "composer": "composer-2.5",
    "composer-2.5-standard": "composer-2.5",
    "grok": "grok-4.7-high",
    "grok-4.7": "grok-4.7-high",
    "grok-4.7-standard": "grok-4.7-high",
    "opus": "claude-4.5-opus-high-thinking",
    "sonnet": "claude-sonnet-5-5-high",
    "gpt": "gpt-5.6-sol-medium",
}

PREFIX_TO_SLUG = {
    "grok": "grok-4.7-high",
    "opus": "claude-4.5-opus-high-thinking",
    "sonnet": "claude-sonnet-5-5-high",
    "gpt": "gpt-5.6-sol-medium",
}

DEFAULT_CONCURRENCY = 3
DEFAULT_IMPLEMENTATION_MODEL = "composer-2.5"
DEFAULT_REVIEW_MODEL = "composer-2.5"
DEFAULT_MAX_FIX_ROUNDS = 2
DEFAULT_ESCALATION_ENABLED = True
DEFAULT_ESCALATION_PREMIUM = "grok-4.7-high"
DEFAULT_ESCALATION_MAX_PER_ISSUE = 1
DEFAULT_ESCALATION_MAX_PER_BATCH = 2
DEFAULT_COMPOSER_ATTEMPTS_BEFORE_ESCALATION = 1
DEFAULT_ALTERNATE_SLUG = "claude-sonnet-5-5-high"

FAST_MODE_NOTE = (
    "Cursor Fast mode is a UI-only toggle; this pipeline cannot enforce Standard vs Fast. "
    "Keep Fast OFF in the model picker. Task API accepts model slugs only — speed is not "
    "a separate parameter."
)


@dataclass
class ResolvedBatchConfig:
    concurrency: int = DEFAULT_CONCURRENCY
    implementation_model: str = DEFAULT_IMPLEMENTATION_MODEL
    review_model: str = DEFAULT_REVIEW_MODEL
    max_fix_rounds: int = DEFAULT_MAX_FIX_ROUNDS
    escalation_enabled: bool = DEFAULT_ESCALATION_ENABLED
    escalation_premium_slug: str = DEFAULT_ESCALATION_PREMIUM
    escalation_max_per_issue: int = DEFAULT_ESCALATION_MAX_PER_ISSUE
    escalation_max_per_batch: int = DEFAULT_ESCALATION_MAX_PER_BATCH
    composer_attempts_before_escalation: int = DEFAULT_COMPOSER_ATTEMPTS_BEFORE_ESCALATION
    implementation_slug_verified: bool = True
    review_slug_verified: bool = True
    escalation_slug_verified: bool = True
    fast_mode_enforcement: str = "ui-only"
    sources: dict[str, str] = field(default_factory=dict)

    def to_effective_dict(self) -> dict:
        payload = asdict(self)
        payload["fast_mode_note"] = FAST_MODE_NOTE
        payload["implementation_model_selection"] = (
            "verified" if self.implementation_slug_verified else "requested-unverified"
        )
        payload["review_model_selection"] = (
            "verified" if self.review_slug_verified else "requested-unverified"
        )
        payload["escalation_model_selection"] = (
            "verified" if self.escalation_slug_verified else "requested-unverified"
        )
        return payload


def is_fast_slug(slug: str) -> bool:
    lowered = slug.strip().lower()
    if lowered in FAST_ONLY_SLUGS:
        return True
    return lowered.endswith("-fast") or "high-fast" in lowered


def normalize_model_slug(raw: str, *, label: str = "model") -> str:
    text = raw.strip().lower()
    if not text:
        raise GraphError(f"{label} cannot be empty")
    if text in {"inherit", "composer", "default", "none"}:
        return DEFAULT_IMPLEMENTATION_MODEL
    if is_fast_slug(text):
        raise GraphError(
            f"{label} {raw!r} is a Fast variant; use standard-speed slugs only "
            f"(e.g. composer-2.5, grok-4.7-high)"
        )
    slug = SLUG_ALIASES.get(text, text)
    return slug


def validate_worker_slug(raw: str, *, label: str) -> tuple[str, bool]:
    """Return canonical slug and whether it is verified for Task selection."""

    slug = normalize_model_slug(raw, label=label)
    verified = slug in STANDARD_VERIFIED_SLUGS
    if not verified:
        raise GraphError(
            f"unsupported {label}: {raw!r} (resolved {slug!r}). "
            f"Supported standard slugs: {', '.join(sorted(STANDARD_VERIFIED_SLUGS))}"
        )
    return slug, verified


def resolve_batch_config(
    *,
    repo_root: Path | None,
    queue_concurrency: int | None = None,
    queue_max_fix_rounds: int | None = None,
    queue_implementation_model: str | None = None,
    queue_review_model: str | None = None,
    queue_escalation_enabled: bool | None = None,
    queue_escalation_premium: str | None = None,
    queue_escalation_max_batch: int | None = None,
    queue_escalation_max_per_issue: int | None = None,
    queue_composer_attempts: int | None = None,
    env: dict[str, str] | None = None,
) -> ResolvedBatchConfig:
    environment = os.environ if env is None else env
    file_payload = load_pipeline_config(repo_root) if repo_root else None
    batch_section = (file_payload or {}).get("batch") or {}
    esc_section = (file_payload or {}).get("escalation") or {}
    if not isinstance(batch_section, dict):
        batch_section = {}
    if not isinstance(esc_section, dict):
        esc_section = {}

    sources: dict[str, str] = {}
    resolved = ResolvedBatchConfig()

    concurrency = int(batch_section.get("concurrency") or DEFAULT_CONCURRENCY)
    sources["concurrency"] = "config"
    if environment.get("PIPELINE_MAX_ACTIVE"):
        concurrency = _positive_int(environment["PIPELINE_MAX_ACTIVE"], "PIPELINE_MAX_ACTIVE")
        sources["concurrency"] = "env"
    if queue_concurrency is not None:
        concurrency = queue_concurrency
        sources["concurrency"] = "queue"
    resolved.concurrency = concurrency

    impl_raw = batch_section.get("implementation_model") or DEFAULT_IMPLEMENTATION_MODEL
    sources["implementation_model"] = "config"
    if queue_implementation_model:
        impl_raw = queue_implementation_model
        sources["implementation_model"] = "queue"
    impl, impl_ok = validate_worker_slug(str(impl_raw), label="Implementation model")
    resolved.implementation_model = impl
    resolved.implementation_slug_verified = impl_ok

    review_raw = batch_section.get("review_model") or DEFAULT_REVIEW_MODEL
    sources["review_model"] = "config"
    if queue_review_model:
        review_raw = queue_review_model
        sources["review_model"] = "queue"
    review, review_ok = validate_worker_slug(str(review_raw), label="Review model")
    resolved.review_model = review
    resolved.review_slug_verified = review_ok

    max_fix = int(batch_section.get("max_fix_rounds") or DEFAULT_MAX_FIX_ROUNDS)
    sources["max_fix_rounds"] = "config"
    if environment.get("PIPELINE_MAX_FIX_ROUNDS"):
        max_fix = _positive_int(environment["PIPELINE_MAX_FIX_ROUNDS"], "PIPELINE_MAX_FIX_ROUNDS")
        sources["max_fix_rounds"] = "env"
    if queue_max_fix_rounds is not None:
        max_fix = queue_max_fix_rounds
        sources["max_fix_rounds"] = "queue"
    resolved.max_fix_rounds = max_fix

    enabled = _coerce_bool(esc_section.get("enabled"), default=DEFAULT_ESCALATION_ENABLED)
    sources["escalation_enabled"] = "config"
    env_esc = _bool_env("PIPELINE_ESCALATION_ENABLED")
    if env_esc is not None:
        enabled = env_esc
        sources["escalation_enabled"] = "env"
    if queue_escalation_enabled is not None:
        enabled = queue_escalation_enabled
        sources["escalation_enabled"] = "queue"
    resolved.escalation_enabled = enabled

    premium_raw = esc_section.get("premium_slug") or DEFAULT_ESCALATION_PREMIUM
    sources["escalation_premium_slug"] = "config"
    if environment.get("PIPELINE_ESCALATION_PREMIUM_SLUG"):
        premium_raw = environment["PIPELINE_ESCALATION_PREMIUM_SLUG"]
        sources["escalation_premium_slug"] = "env"
    if queue_escalation_premium:
        premium_raw = queue_escalation_premium
        sources["escalation_premium_slug"] = "queue"
    try:
        premium, premium_ok = validate_worker_slug(str(premium_raw), label="Escalation model")
    except GraphError:
        premium = normalize_model_slug(str(premium_raw), label="Escalation model")
        premium_ok = False
    resolved.escalation_premium_slug = premium
    resolved.escalation_slug_verified = premium_ok

    max_per_issue = int(esc_section.get("max_per_issue") or DEFAULT_ESCALATION_MAX_PER_ISSUE)
    if queue_escalation_max_per_issue is not None:
        max_per_issue = queue_escalation_max_per_issue
        sources["escalation_max_per_issue"] = "queue"
    resolved.escalation_max_per_issue = _non_negative_int(max_per_issue, "Max premium attempts per issue")

    max_batch = int(esc_section.get("max_per_batch") or DEFAULT_ESCALATION_MAX_PER_BATCH)
    sources["escalation_max_per_batch"] = "config"
    env_batch = _int_env("PIPELINE_ESCALATION_MAX_BATCH")
    if env_batch is not None:
        max_batch = env_batch
        sources["escalation_max_per_batch"] = "env"
    if queue_escalation_max_batch is not None:
        max_batch = queue_escalation_max_batch
        sources["escalation_max_per_batch"] = "queue"
    resolved.escalation_max_per_batch = _non_negative_int(
        max_batch, "Max premium escalations per batch"
    )

    composer_attempts = int(
        esc_section.get("composer_attempts_before_escalation")
        or DEFAULT_COMPOSER_ATTEMPTS_BEFORE_ESCALATION
    )
    if queue_composer_attempts is not None:
        composer_attempts = queue_composer_attempts
        sources["composer_attempts_before_escalation"] = "queue"
    resolved.composer_attempts_before_escalation = _non_negative_int(
        composer_attempts, "Composer attempts before escalation"
    )

    if resolved.escalation_enabled and not resolved.escalation_slug_verified:
        raise GraphError(
            f"escalation is enabled but escalation model {premium_raw!r} is not a verified "
            "standard-speed Task slug"
        )
    if (
        resolved.escalation_enabled
        and resolved.escalation_max_per_batch == 0
        and queue_escalation_enabled is not False
    ):
        raise GraphError(
            "contradictory escalation settings: enabled with "
            "Max premium escalations per batch: 0"
        )

    resolved.sources = sources
    return resolved


def apply_resolved_config(state, resolved: ResolvedBatchConfig) -> None:
    state.concurrency = resolved.concurrency
    state.max_fix_rounds = resolved.max_fix_rounds
    state.escalation_enabled = resolved.escalation_enabled
    state.escalation_premium_slug = resolved.escalation_premium_slug
    state.escalation_max_per_batch = resolved.escalation_max_per_batch
    state.escalation_max_per_issue = resolved.escalation_max_per_issue
    state.composer_attempts_before_escalation = resolved.composer_attempts_before_escalation
    state.implementation_model_slug = resolved.implementation_model
    state.review_model_slug = resolved.review_model
    state.review_model = "explicit"
    state.effective_config = resolved.to_effective_dict()


def overrides_for_issue(issue) -> dict:
    """Summarize per-issue overrides for batch completion reporting."""

    return {
        "issue": issue.key,
        "model_slug": issue.model_slug,
        "issue_model_override": issue.issue_model_override,
        "escalation_disabled": issue.escalation_disabled,
        "queue_prefix": issue.queue_prefix,
        "premium_attempts": issue.premium_attempts,
    }


def config_event_detail(resolved: ResolvedBatchConfig) -> str:
    return json.dumps(
        {
            "concurrency": resolved.concurrency,
            "implementation_model": resolved.implementation_model,
            "review_model": resolved.review_model,
            "escalation": resolved.escalation_enabled,
            "escalation_model": resolved.escalation_premium_slug,
        },
        sort_keys=True,
    )


def _coerce_bool(value, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
    return bool(value)


def _bool_env(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _positive_int(value: str | int, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GraphError(f"{label} must be an integer") from exc
    if parsed < 1:
        raise GraphError(f"{label} must be >= 1")
    return parsed


def _non_negative_int(value: str | int, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GraphError(f"{label} must be an integer") from exc
    if parsed < 0:
        raise GraphError(f"{label} must be >= 0")
    return parsed

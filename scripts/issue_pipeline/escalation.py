"""Cost-aware model escalation when review findings persist after correction."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .models import BatchState, IssueRecord

# Subset of Cursor Task slugs this pipeline may assign without silent substitution.
VERIFIED_TASK_SLUGS = frozenset(
    {
        "composer-2.5",
        "composer-2.5-fast",
        "grok-4.7-high",
        "cursor-grok-4.6-high-fast",
        "claude-4.5-opus-high-thinking",
        "claude-sonnet-5-5-high",
        "gpt-5.6-sol-medium",
    }
)

DEFAULT_PREMIUM_SLUG = "grok-4.7-high"
DEFAULT_MAX_PER_ISSUE = 1
DEFAULT_MAX_PER_BATCH = 2

_INFRA_REVIEW_DETAIL = re.compile(
    r"(malformed|pytest result is not passed|tasks are not fully checked|"
    r"Reviewed-SHA does not match|verification is required|unexpected verdict)",
    re.I,
)

_FINDING_LINE = re.compile(r"(?m)^\s*(?:[-*]|\d+\.)\s+(.+)$")
_FINDING_ID = re.compile(r"\b(?:finding|issue|bug|gap)[-\s#]*(\w+)\b", re.I)


@dataclass
class EscalationPolicy:
    enabled: bool = False
    premium_slug: str = DEFAULT_PREMIUM_SLUG
    max_per_issue: int = DEFAULT_MAX_PER_ISSUE
    max_per_batch: int = DEFAULT_MAX_PER_BATCH
    slug_verified: bool = False

    def premium_available(self, state: BatchState, issue: IssueRecord) -> bool:
        if not self.enabled:
            return False
        if not self.slug_verified:
            return False
        if issue.queue_prefix:
            return False
        if issue.premium_attempts >= self.max_per_issue:
            return False
        if state.escalation_batch_count >= self.max_per_batch:
            return False
        return True


def load_escalation_policy(
    *,
    queue_enabled: bool | None = None,
    queue_premium: str | None = None,
    queue_max_batch: int | None = None,
    config_payload: dict | None = None,
) -> EscalationPolicy:
    """Resolve policy: env overrides config overrides queue headers."""

    config = (config_payload or {}).get("escalation") or {}
    if not isinstance(config, dict):
        config = {}

    enabled = _bool_env("PIPELINE_ESCALATION_ENABLED")
    if enabled is None:
        enabled = bool(config.get("enabled"))

    premium = (
        os.environ.get("PIPELINE_ESCALATION_PREMIUM_SLUG")
        or queue_premium
        or config.get("premium_slug")
        or DEFAULT_PREMIUM_SLUG
    )
    max_batch = _int_env("PIPELINE_ESCALATION_MAX_BATCH")
    if max_batch is None:
        max_batch = queue_max_batch
    if max_batch is None:
        max_batch = int(config.get("max_per_batch") or DEFAULT_MAX_PER_BATCH)

    max_per_issue = int(config.get("max_per_issue") or DEFAULT_MAX_PER_ISSUE)

    if queue_enabled is not None:
        enabled = queue_enabled

    slug = str(premium).strip()
    verified = slug in VERIFIED_TASK_SLUGS

    return EscalationPolicy(
        enabled=bool(enabled),
        premium_slug=slug,
        max_per_issue=max(1, max_per_issue),
        max_per_batch=max(0, max_batch),
        slug_verified=verified,
    )


def normalize_findings(text: str) -> set[str]:
    if not text or text.strip().lower() in {"none", "fix first", "not close"}:
        return set()
    tokens: set[str] = set()
    for match in _FINDING_LINE.finditer(text):
        line = _normalize_token(match.group(1))
        if line:
            tokens.add(line)
    if not tokens:
        for chunk in re.split(r"[;\n]+", text):
            line = _normalize_token(chunk)
            if line and len(line) > 12:
                tokens.add(line)
    for match in _FINDING_ID.finditer(text):
        tokens.add(f"id:{match.group(1).lower()}")
    return tokens


def findings_overlap(previous: str, current: str) -> bool:
    prev = normalize_findings(previous)
    curr = normalize_findings(current)
    if not prev or not curr:
        return False
    shared = prev & curr
    return len(shared) >= max(1, len(prev) // 2)


def classify_new_vs_recurring(previous: str, current: str) -> tuple[list[str], list[str]]:
    prev = normalize_findings(previous)
    curr = normalize_findings(current)
    recurring = sorted(prev & curr)
    new = sorted(curr - prev)
    return recurring, new


def is_infrastructure_review_failure(reason: str) -> bool:
    return bool(_INFRA_REVIEW_DETAIL.search(reason or ""))


def evaluate_premium_escalation(
    state: BatchState,
    issue: IssueRecord,
    *,
    verdict: str,
    findings: str,
    policy: EscalationPolicy,
    infrastructure: bool = False,
) -> dict | None:
    """Return an escalation decision dict, or None when escalation does not apply."""

    if infrastructure or verdict not in {"FIX FIRST", "NOT CLOSE"}:
        return None
    if issue.fix_round < 1:
        return None
    previous = issue.last_review_findings or ""
    if not findings_overlap(previous, findings):
        return None
    if not policy.premium_available(state, issue):
        reason = "escalation disabled or budget exhausted"
        if not policy.enabled:
            reason = "escalation disabled"
        elif not policy.slug_verified:
            reason = f"premium slug not verified: {policy.premium_slug}"
        elif issue.queue_prefix:
            reason = "explicit queue model override preserved"
        elif issue.premium_attempts >= policy.max_per_issue:
            reason = "per-issue premium budget exhausted"
        elif state.escalation_batch_count >= policy.max_per_batch:
            reason = "batch premium budget exhausted"
        return {"escalate": False, "reason": reason}

    recurring, new = classify_new_vs_recurring(previous, findings)
    return {
        "escalate": True,
        "trigger": "persistent_substantive_finding",
        "original_model": issue.model_slug or "composer-inherit",
        "escalated_model": policy.premium_slug,
        "slug_verified": policy.slug_verified,
        "recurring_findings": recurring,
        "new_findings": new,
        "fix_round": issue.fix_round,
    }


def apply_escalation(
    state: BatchState,
    issue: IssueRecord,
    decision: dict,
) -> None:
    """Mutate issue/state when a premium correction is scheduled."""

    if not decision.get("escalate"):
        return
    slug = decision["escalated_model"]
    issue.premium_pending = True
    issue.model_slug = slug
    state.escalation_batch_count += 1
    record = {
        "at": state.updated_at,
        "trigger": decision["trigger"],
        "original_model": decision["original_model"],
        "escalated_model": slug,
        "slug_verified": decision["slug_verified"],
        "fix_round": decision["fix_round"],
        "recurring_findings": decision.get("recurring_findings") or [],
        "new_findings": decision.get("new_findings") or [],
        "result": "scheduled",
    }
    issue.escalation_records.append(record)
    state.escalation_records.append({**record, "issue": issue.key})
    state.event(
        issue.key,
        "premium-escalation",
        f"{slug} recurring={len(record['recurring_findings'])}",
    )


def record_premium_outcome(
    state: BatchState,
    issue: IssueRecord,
    *,
    success: bool,
    reviewer_verdict: str | None = None,
    extra_attempts: int = 0,
) -> None:
    if not issue.escalation_records:
        return
    last = issue.escalation_records[-1]
    last["result"] = "recovered" if success else "failed"
    last["reviewer_verdict"] = reviewer_verdict
    last["extra_attempts"] = extra_attempts
    for batch_record in reversed(state.escalation_records):
        if batch_record.get("issue") == issue.key and batch_record.get("result") == "scheduled":
            batch_record.update(last)
            break


def _normalize_token(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    cleaned = re.sub(r"`[^`]+`", "", cleaned)
    return cleaned[:240]


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

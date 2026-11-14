"""Structured failure reasons for scheduling, escalation, and reporting."""

from __future__ import annotations

import re
from typing import Any

CODE_DEFECT = "code-defect"
INTEGRATION_CONFLICT = "integration-conflict"
TEST_ENVIRONMENT = "test-environment"
INFRASTRUCTURE = "infrastructure"
HANDOFF_MALFORMED = "handoff-malformed"

VALID = frozenset(
    {
        CODE_DEFECT,
        INTEGRATION_CONFLICT,
        TEST_ENVIRONMENT,
        INFRASTRUCTURE,
        HANDOFF_MALFORMED,
    }
)

_NON_BUDGET = {TEST_ENVIRONMENT, INFRASTRUCTURE, HANDOFF_MALFORMED}

_ENV_CLAIM = re.compile(
    r"\b(flaky|intermittent|rate\s*limit|503|timeout|environment|infra|docker\s+not\s+running|"
    r"connection\s+refused|temporar(?:y|ily)\s+unavailable)\b",
    re.I,
)
_FAILED_TEST = re.compile(r"\b(failed|failure|error|assert(?:ion)?\s+failed)\b", re.I)
_VERIFIED_LOCK = re.compile(r"issue-pipeline\s+(verify|lock\s+exec)", re.I)


def consumes_fix_budget(category: str | None) -> bool:
    if not category:
        return True
    return category not in _NON_BUDGET and category != INTEGRATION_CONFLICT


def consumes_premium_budget(category: str | None) -> bool:
    return category == CODE_DEFECT


def integration_conflict_may_escalate(attempts: int, *, max_attempts: int = 2) -> bool:
    return attempts >= max_attempts


def record_failure(
    issue,
    *,
    category: str,
    evidence: str,
    action: str,
    at: str,
) -> None:
    if category not in VALID:
        category = CODE_DEFECT
    issue.last_failure_category = category
    entry: dict[str, Any] = {
        "at": at,
        "category": category,
        "evidence": (evidence or "")[:2000],
        "action": action,
        "consumes_fix_budget": consumes_fix_budget(category),
        "consumes_premium_budget": consumes_premium_budget(category),
    }
    issue.failure_records.append(entry)


def classify_ci_failure(
    reason: str,
    *,
    failed_checks: tuple = (),
    verification: str | None = None,
) -> str:
    """Default to code-defect unless verified environmental evidence exists."""

    text = " ".join(
        filter(
            None,
            [
                reason,
                verification or "",
                " ".join(getattr(check, "name", "") for check in failed_checks),
            ],
        )
    )
    if _env_claim_without_test_failure(text, verification):
        return TEST_ENVIRONMENT
    if "integration" in reason.lower() and "conflict" in reason.lower():
        return INTEGRATION_CONFLICT
    return CODE_DEFECT


def classify_review_malformed(reason: str) -> str:
    lowered = (reason or "").lower()
    if "pytest" in lowered or "tasks are not" in lowered or "reviewed-sha" in lowered:
        return HANDOFF_MALFORMED
    if any(
        token in lowered
        for token in ("malformed", "unexpected verdict", "verification is required")
    ):
        return HANDOFF_MALFORMED
    return INFRASTRUCTURE


def classify_implement_blocked(blocker: str, *, verification: str | None = None) -> str:
    text = f"{blocker} {verification or ''}"
    if _env_claim_without_test_failure(text, verification):
        return TEST_ENVIRONMENT
    if "conflict" in text.lower() and "merge" in text.lower():
        return INTEGRATION_CONFLICT
    return CODE_DEFECT


def _env_claim_without_test_failure(text: str, verification: str | None) -> bool:
    if not text.strip():
        return False
    if _FAILED_TEST.search(text) and not _ENV_CLAIM.search(text):
        return False
    if not _ENV_CLAIM.search(text):
        return False
    if verification and _VERIFIED_LOCK.search(verification) and _FAILED_TEST.search(text):
        return False
    return True

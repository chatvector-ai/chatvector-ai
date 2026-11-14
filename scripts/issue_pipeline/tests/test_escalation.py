from scripts.issue_pipeline.escalation import (
    VERIFIED_TASK_SLUGS,
    EscalationPolicy,
    evaluate_premium_escalation,
    findings_overlap,
    is_infrastructure_review_failure,
    load_escalation_policy,
    normalize_findings,
)
from scripts.issue_pipeline.models import NEEDS_FIX, BatchState, IssueRecord
from scripts.issue_pipeline.scheduler import apply_review_handoff, claim

from .support import plan, snapshot


def test_findings_overlap_detects_repeated_substance():
    prev = "- Backend route does not enforce auth on DELETE\n- Missing test for empty payload"
    curr = "- Backend route does not enforce auth on DELETE\n- Frontend still shows stale preset"
    assert findings_overlap(prev, curr)
    recurring = normalize_findings(prev) & normalize_findings(curr)
    assert any("auth" in item for item in recurring)


def test_infrastructure_review_failure_is_not_escalation_evidence():
    reason = "pytest result is not passed: 1409 passed, 2 skipped"
    assert is_infrastructure_review_failure(reason)


def test_unsupported_premium_slug_disables_verified_escalation(monkeypatch):
    monkeypatch.setenv("PIPELINE_ESCALATION_ENABLED", "1")
    monkeypatch.setenv("PIPELINE_ESCALATION_PREMIUM_SLUG", "not-a-real-slug")
    policy = load_escalation_policy()
    assert policy.enabled is True
    assert policy.slug_verified is False


def test_premium_escalation_after_persistent_finding():
    state = BatchState(
        escalation_enabled=True,
        escalation_premium_slug="grok-4.7-high",
        escalation_max_per_batch=2,
    )
    issue = IssueRecord(
        key="42",
        number=42,
        state=NEEDS_FIX,
        fix_round=1,
        last_review_findings="- Service returns 500 for valid payload",
    )
    state.issues["42"] = issue
    policy = EscalationPolicy(
        enabled=True,
        premium_slug="grok-4.7-high",
        slug_verified="grok-4.7-high" in VERIFIED_TASK_SLUGS,
    )
    decision = evaluate_premium_escalation(
        state,
        issue,
        verdict="FIX FIRST",
        findings="- Service returns 500 for valid payload",
        policy=policy,
    )
    assert decision is not None
    assert decision["escalate"] is True
    assert decision["escalated_model"] == "grok-4.7-high"


def test_no_escalation_on_first_review_failure():
    state = BatchState(escalation_enabled=True, escalation_premium_slug="grok-4.7-high")
    issue = IssueRecord(key="1", number=1, fix_round=0)
    state.issues["1"] = issue
    policy = EscalationPolicy(enabled=True, premium_slug="grok-4.7-high", slug_verified=True)
    decision = evaluate_premium_escalation(
        state,
        issue,
        verdict="FIX FIRST",
        findings="missing validation",
        policy=policy,
    )
    assert decision is None


def test_batch_premium_budget_exhaustion():
    state = BatchState(
        escalation_enabled=True,
        escalation_premium_slug="grok-4.7-high",
        escalation_max_per_batch=1,
        escalation_batch_count=1,
    )
    issue = IssueRecord(
        key="9",
        number=9,
        fix_round=1,
        last_review_findings="- Same blocker",
    )
    state.issues["9"] = issue
    policy = EscalationPolicy(
        enabled=True,
        premium_slug="grok-4.7-high",
        max_per_batch=1,
        slug_verified=True,
    )
    decision = evaluate_premium_escalation(
        state,
        issue,
        verdict="FIX FIRST",
        findings="- Same blocker remains",
        policy=policy,
    )
    assert decision is not None
    assert decision["escalate"] is False


def test_premium_recovery_and_failed_premium_review_block():
    state = plan("1\n", [snapshot(1, body="")])
    state.escalation_enabled = True
    state.escalation_premium_slug = "grok-4.7-high"
    issue = state.issues["1"]
    issue.base_sha = "abc123def4567890"
    sha = "abc123def4567890"
    claim(state, "1", "implement", worker_id="w1")
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "FIX FIRST",
            "Reviewed-SHA": sha,
            "Base-SHA": sha,
            "Findings": "- Missing retries",
            "Verification": "pytest",
            "Pytest": "passed",
            "Tasks-checked": "1/1",
        },
        head_sha=sha,
    )
    issue.fix_round = 1
    issue.last_review_findings = "- Missing retries"
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "FIX FIRST",
            "Reviewed-SHA": sha,
            "Base-SHA": sha,
            "Findings": "- Missing retries",
            "Verification": "pytest",
            "Pytest": "passed",
            "Tasks-checked": "1/1",
        },
        head_sha=sha,
    )
    assert issue.premium_pending is True
    assert issue.model_slug == "grok-4.7-high"
    claim(state, "1", "implement", worker_id="w2")
    assert issue.last_implement_premium is True
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "READY",
            "Reviewed-SHA": sha,
            "Base-SHA": sha,
            "Findings": "none",
            "Verification": "pytest",
            "Pytest": "passed",
            "Tasks-checked": "1/1",
        },
        head_sha=sha,
    )
    assert issue.state == "ready-to-publish"

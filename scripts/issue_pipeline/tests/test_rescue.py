from scripts.issue_pipeline.models import BLOCKED, NEEDS_FIX, REVIEWING, transition
from scripts.issue_pipeline.scheduler import (
    apply_review_handoff,
    authorize_premium_rescue,
    claim,
)
from scripts.issue_pipeline.tests.support import plan, snapshot


def _blocking_review_handoff(sha: str) -> dict[str, str]:
    return {
        "Verdict": "FIX FIRST",
        "Reviewed-SHA": sha,
        "Base-SHA": sha,
        "Findings": "- Drawer still shows inherited concrete numbers before explicit user choice",
        "Verification": "scripts/issue-pipeline verify -- pytest backend/tests -q",
        "Pytest": "passed",
        "Tasks-checked": "1/1",
    }


def test_premium_escalation_when_budget_exhausted_with_new_findings():
    state = plan("Max fix rounds: 2\n1\n", [snapshot(1)])
    state.escalation_enabled = True
    state.escalation_premium_slug = "grok-4.7-high"
    sha = "abc123def4567890"
    issue = state.issues["1"]
    issue.base_sha = sha
    issue.state = REVIEWING
    issue.fix_round = 2
    issue.claimed = False
    issue.last_review_findings = "- earlier unrelated label issue"
    apply_review_handoff(
        state,
        "1",
        {
            **_blocking_review_handoff(sha),
            "Findings": "- New acceptance gap: omitted match count shows a default digit",
        },
        head_sha=sha,
    )
    assert issue.state == NEEDS_FIX
    assert issue.premium_pending is True
    assert issue.model_slug == "grok-4.7-high"


def test_rescue_from_fix_limit_schedules_premium_without_replaying_review():
    state = plan("Max fix rounds: 2\n1\n", [snapshot(1)])
    state.escalation_enabled = True
    state.escalation_premium_slug = "grok-4.7-high"
    state.escalation_batch_count = 0
    issue = state.issues["1"]
    sha = "abc123def4567890"
    issue.base_sha = sha
    issue.state = BLOCKED
    issue.reason_code = "fix-limit"
    issue.fix_round = 2
    issue.findings = "- Actionable defect remains"
    issue.blocker = issue.findings
    issue.blocked_idle_since = state.updated_at

    authorize_premium_rescue(state, "1", note="recovery-630")
    assert issue.state == NEEDS_FIX
    assert issue.premium_pending is True
    assert issue.reason_code == "premium-rescue"
    assert issue.fix_round == 2
    assert issue.operator_rescue_at is not None
    assert state.escalation_batch_count == 1
    assert any(event["event"] == "rescue-authorized" for event in state.events)

    authorize_premium_rescue(state, "1")
    assert issue.premium_pending is True

    claim(state, "1", "implement", worker_id="630-rescue-1")
    assert issue.premium_attempts == 1
    assert issue.last_implement_premium is True
    assert issue.fix_round == 2


def test_rescue_rejects_duplicate_while_still_blocked():
    state = plan("1\n", [snapshot(1)])
    state.escalation_enabled = True
    issue = state.issues["1"]
    issue.state = BLOCKED
    issue.reason_code = "fix-limit"
    issue.findings = "- Still broken"
    issue.blocker = issue.findings
    issue.operator_rescue_at = "2026-11-08T00:00:00+00:00"
    import pytest
    from scripts.issue_pipeline.models import TransitionError

    with pytest.raises(TransitionError):
        authorize_premium_rescue(state, "1")


def test_malformed_review_does_not_escalate():
    state = plan("Max fix rounds: 2\n1\n", [snapshot(1)])
    state.escalation_enabled = True
    issue = state.issues["1"]
    sha = "abc123def4567890"
    issue.base_sha = sha
    issue.state = REVIEWING
    issue.fix_round = 2
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "FIX FIRST",
            "Reviewed-SHA": sha,
            "Base-SHA": sha,
            "Findings": "FIX FIRST",
            "Verification": "scripts/issue-pipeline verify -- pytest backend/tests -q",
            "Pytest": "passed",
            "Tasks-checked": "1/1",
        },
        head_sha=sha,
    )
    assert issue.state == REVIEWING
    assert issue.premium_pending is False
    assert state.escalation_batch_count == 0


def test_premium_rescue_followed_by_review_ready():
    state = plan("Max fix rounds: 2\n1\n", [snapshot(1)])
    state.escalation_enabled = True
    sha = "abc123def4567890"
    issue = state.issues["1"]
    issue.base_sha = sha
    claim(state, "1", "implement", worker_id="w1")
    transition(issue, REVIEWING)
    apply_review_handoff(state, "1", _blocking_review_handoff(sha), head_sha=sha)
    issue.fix_round = 2
    issue.state = REVIEWING
    apply_review_handoff(
        state,
        "1",
        {
            **_blocking_review_handoff(sha),
            "Findings": "- Same substantive auth gap",
        },
        head_sha=sha,
    )
    assert issue.premium_pending
    claim(state, "1", "implement", worker_id="premium")
    transition(issue, REVIEWING)
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "READY",
            "Reviewed-SHA": sha,
            "Base-SHA": sha,
            "Findings": "none",
            "Verification": "scripts/issue-pipeline verify -- pytest backend/tests -q",
            "Pytest": "passed",
            "Tasks-checked": "1/1",
        },
        head_sha=sha,
    )
    assert issue.state == "ready-to-publish"

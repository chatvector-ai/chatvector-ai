from scripts.issue_pipeline.failure_categories import (
    CODE_DEFECT,
    HANDOFF_MALFORMED,
    TEST_ENVIRONMENT,
    classify_ci_failure,
    classify_review_malformed,
    consumes_fix_budget,
    consumes_premium_budget,
)
from scripts.issue_pipeline.models import REVIEWING, BatchState, IssueRecord
from scripts.issue_pipeline.scheduler import apply_review_handoff, claim

from .support import plan, snapshot


def test_handoff_malformed_does_not_consume_fix_budget():
    assert not consumes_fix_budget(HANDOFF_MALFORMED)
    assert not consumes_premium_budget(HANDOFF_MALFORMED)


def test_environment_claim_requires_evidence():
    assert (
        classify_ci_failure("flaky 503 from registry", verification="manual retry suggested")
        == TEST_ENVIRONMENT
    )
    assert classify_ci_failure("Backend Tests failed: assertion error") == CODE_DEFECT


def test_malformed_pytest_records_handoff_category():
    state = plan("1\n", [snapshot(1)])
    state.issues["1"].state = REVIEWING
    state.issues["1"].base_sha = "base"
    claim(state, "1", "review", worker_id="worker")
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "READY",
            "Reviewed-SHA": "abc123def4567890",
            "Base-SHA": "base",
            "Pytest": "not-a-summary",
            "Tasks-checked": "1/1",
            "Verification": "scripts/issue-pipeline verify -- pytest backend/tests -q",
        },
        head_sha="abc123def4567890",
    )
    issue = state.issues["1"]
    assert issue.state == REVIEWING
    assert classify_review_malformed(issue.notes or "") == HANDOFF_MALFORMED
    assert issue.fix_round == 0

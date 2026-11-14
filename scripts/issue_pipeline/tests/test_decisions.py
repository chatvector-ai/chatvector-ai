from scripts.issue_pipeline.decisions import (
    CheckResult,
    PrView,
    ReviewBinding,
    admin_bypass_allowed,
    decide,
)
from scripts.issue_pipeline.github import (
    build_merge_command,
    classify_merge_failure,
    parse_protection_checks,
    parse_rules_required_checks,
    render_merge_message,
    render_pr_body,
)
from scripts.issue_pipeline.models import IssueRecord


def _pr(**overrides) -> PrView:
    base = dict(
        number=7,
        state="OPEN",
        draft=False,
        head_sha="a" * 40,
        base_sha="b" * 40,
        base_ref="main",
        mergeable="MERGEABLE",
        merge_state="CLEAN",
        review_decision="APPROVED",
        checks=(CheckResult("Backend Tests", "success", "https://ci.example/backend"),),
    )
    base.update(overrides)
    return PrView(**base)


def _binding(**overrides) -> ReviewBinding:
    base = dict(reviewed_sha="a" * 40, base_sha="b" * 40)
    base.update(overrides)
    return ReviewBinding(**base)


def test_pending_missing_and_failed_checks_do_not_merge():
    required = ["Backend Tests", "Frontend Validation"]
    pending = decide(
        _pr(checks=(CheckResult("Backend Tests", "pending"), CheckResult("Frontend Validation", "success"))),
        _binding(),
        required,
        overlap="same-base",
    )
    missing = decide(
        _pr(checks=(CheckResult("Backend Tests", "success"),)),
        _binding(),
        required,
        overlap="same-base",
    )
    failed = decide(
        _pr(checks=(CheckResult("Backend Tests", "failure", "https://ci.example/fail"),)),
        _binding(),
        ["Backend Tests"],
        overlap="same-base",
    )
    assert pending.action == "wait"
    assert missing.action == "wait"
    assert "missing" in missing.reason
    assert failed.action == "needs-fix"
    assert failed.failed_checks[0].url == "https://ci.example/fail"
    assert failed.use_admin is False


def test_admin_bypass_is_only_the_review_blocker():
    required = ["Backend Tests"]
    review_only = _pr(review_decision="REVIEW_REQUIRED", merge_state="BLOCKED")
    assert admin_bypass_allowed(review_only, _binding(), required, overlap="same-base") is True
    assert decide(review_only, _binding(), required, overlap="same-base").action == "admin-merge"

    refused = [
        _pr(review_decision="REVIEW_REQUIRED", merge_state="BLOCKED", checks=(CheckResult("Backend Tests", "failure"),)),
        _pr(review_decision="REVIEW_REQUIRED", merge_state="BLOCKED", checks=(CheckResult("Backend Tests", "pending"),)),
        _pr(review_decision="REVIEW_REQUIRED", merge_state="BLOCKED", checks=()),
        _pr(review_decision="REVIEW_REQUIRED", merge_state="UNSTABLE"),
        _pr(review_decision="CHANGES_REQUESTED", merge_state="BLOCKED"),
        _pr(review_decision="REVIEW_REQUIRED", merge_state="BLOCKED", head_sha="c" * 40),
        _pr(review_decision="REVIEW_REQUIRED", merge_state="DIRTY", mergeable="CONFLICTING"),
        _pr(review_decision="REVIEW_REQUIRED", merge_state="BLOCKED", draft=True),
    ]
    for pr in refused:
        decision = decide(pr, _binding(), required, overlap="same-base")
        assert decision.use_admin is False
        assert decision.action != "admin-merge"


def test_changed_head_invalidates_approval_even_when_review_is_required():
    decision = decide(
        _pr(head_sha="c" * 40, review_decision="REVIEW_REQUIRED", merge_state="BLOCKED"),
        _binding(),
        ["Backend Tests"],
        overlap="same-base",
    )
    assert decision.action == "invalidate-head"
    assert decision.use_admin is False


def test_unknown_required_checks_and_cancelled_checks_block_merge():
    unknown = decide(_pr(), _binding(), None, overlap="same-base")
    cancelled = decide(
        _pr(checks=(CheckResult("Backend Tests", "cancelled"),)),
        _binding(),
        ["Backend Tests"],
        overlap="same-base",
    )
    assert unknown.action == "block"
    assert "could not be established" in unknown.reason
    assert cancelled.action == "block"
    assert cancelled.action != "needs-fix"


def test_upstream_overlap_requires_rereview_and_disjoint_change_requires_validation():
    moved = _pr(base_sha="c" * 40)
    binding = _binding()
    overlap = decide(moved, binding, ["Backend Tests"], overlap="overlap")
    unknown = decide(moved, binding, ["Backend Tests"], overlap="unknown")
    disjoint = decide(moved, binding, ["Backend Tests"], overlap="disjoint")
    validated = decide(
        moved,
        _binding(integration_base_sha="c" * 40, integration_result="pass"),
        ["Backend Tests"],
        overlap="disjoint",
    )
    assert overlap.action == "needs-rereview"
    assert unknown.action == "needs-rereview"
    assert disjoint.action == "needs-revalidation"
    assert validated.action == "merge"


def test_merge_command_is_squash_and_sha_bound():
    command = build_merge_command(
        "chatvector-ai/chatvector-ai",
        12,
        admin=False,
        sha="a" * 40,
        subject="feat(backend): add",
        body="Closes #12\n",
    )
    assert "--squash" in command
    assert "--match-head-commit" in command
    assert "a" * 40 in command
    assert "--admin" not in command
    assert "--merge" not in command
    assert "--rebase" not in command
    admin = build_merge_command(
        "chatvector-ai/chatvector-ai",
        12,
        admin=True,
        sha="a" * 40,
        subject="feat(backend): add",
        body="body",
    )
    assert admin.count("--admin") == 1


def test_mixed_review_and_check_failure_is_not_an_admin_excuse():
    text = "failing checks: Backend Tests; also review required"
    assert classify_merge_failure(text) == "checks"
    assert classify_merge_failure("at least 1 approving review is required") == "review_required"
    assert classify_merge_failure("added to merge queue") == "queue"


def test_ruleset_parser_does_not_invent_checks():
    assert parse_rules_required_checks([{"type": "pull_request"}]) is None
    assert parse_rules_required_checks(
        [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "Backend Tests"}]}}]
    ) == ["Backend Tests"]
    assert parse_protection_checks({"contexts": ["Backend Tests"], "checks": []}) == ["Backend Tests"]


def test_audit_body_omits_closes_and_issue_body_includes_it():
    issue = IssueRecord(
        key="12",
        number=12,
        title="Add export",
        summary="Add export",
        reviewed_sha="a" * 40,
        base_sha="b" * 40,
        findings="none",
        verification="pytest passed",
        areas=["backend"],
    )
    assert "Closes #12" in render_pr_body(issue)
    subject, body = render_merge_message(issue)
    assert subject.startswith("feat(backend):")
    assert "Closes #12" in body
    audit = IssueRecord(
        key="AUDIT-001",
        work_id="AUDIT-001",
        title="Fix metric",
        mode="audit-fix",
        audit_report="docs/audits/report.md",
        reviewed_sha="a" * 40,
        base_sha="b" * 40,
        findings="none",
        verification="pytest passed",
    )
    rendered = render_pr_body(audit)
    assert "Closes #" not in rendered
    assert "AUDIT-001" in rendered
    assert "docs/audits/report.md" in rendered

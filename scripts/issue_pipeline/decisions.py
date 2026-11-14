"""Pure merge gate. Callers must not merge unless this returns a merge action."""

from __future__ import annotations

from dataclasses import dataclass

FAILURES = {"failure", "timed_out", "startup_failure", "action_required"}
PENDING = {"pending", "queued", "in_progress"}
# Required checks in these states block the merge and do not start a code fix.
UNACCEPTABLE = {"skipped", "cancelled", "stale", "neutral", "unknown"}

RANK = {
    "failure": 5,
    "pending": 4,
    "unknown": 3,
    "stale": 3,
    "cancelled": 3,
    "skipped": 3,
    "neutral": 3,
    "success": 1,
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    conclusion: str
    url: str = ""


@dataclass(frozen=True)
class PrView:
    number: int
    state: str
    draft: bool
    head_sha: str
    base_sha: str
    base_ref: str
    mergeable: str
    merge_state: str
    review_decision: str
    checks: tuple[CheckResult, ...] = ()
    url: str = ""
    merge_sha: str | None = None


@dataclass(frozen=True)
class ReviewBinding:
    reviewed_sha: str | None
    base_sha: str | None
    integration_base_sha: str | None = None
    integration_result: str | None = None


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    failed_checks: tuple[CheckResult, ...] = ()
    use_admin: bool = False


def combine_checks(checks: list[CheckResult]) -> dict[str, CheckResult]:
    """Collapse duplicate names to the worst conclusion."""

    chosen: dict[str, CheckResult] = {}
    for check in checks:
        current = chosen.get(check.name)
        if current is None or RANK.get(check.conclusion, 3) > RANK.get(current.conclusion, 3):
            chosen[check.name] = check
    return chosen


def admin_bypass_allowed(
    pr: PrView,
    binding: ReviewBinding,
    required: list[str] | None,
    *,
    overlap: str,
) -> bool:
    """True only when a missing human approval is the sole remaining blocker."""

    if pr.state != "OPEN" or pr.draft:
        return False
    if pr.review_decision != "REVIEW_REQUIRED":
        return False
    if pr.merge_state != "BLOCKED" or pr.mergeable != "MERGEABLE":
        return False
    if not binding.reviewed_sha or pr.head_sha != binding.reviewed_sha:
        return False
    if pr.base_ref not in {"main", "refs/heads/main"}:
        return False
    if required is None:
        return False
    if not _required_all_success(pr, required):
        return False
    if not _base_allows_merge(pr, binding, overlap):
        return False
    return True


def decide(
    pr: PrView,
    binding: ReviewBinding,
    required: list[str] | None,
    *,
    overlap: str,
    independent_review: str | None = None,
) -> Decision:
    """Decide what finalize may do. `overlap` is overlap, disjoint, unknown, or same-base."""

    if independent_review and independent_review != "READY":
        return Decision("block", f"independent review verdict is {independent_review}")

    if pr.state == "MERGED":
        return Decision("already-merged", "pull request is already merged")
    if pr.state != "OPEN":
        return Decision("block", f"pull request is {pr.state}")
    if pr.draft:
        return Decision("block", "pull request is draft")
    if not binding.reviewed_sha:
        return Decision("block", "no reviewed SHA is recorded")
    if pr.head_sha != binding.reviewed_sha:
        return Decision(
            "invalidate-head",
            f"remote head {pr.head_sha} does not match reviewed {binding.reviewed_sha}",
        )
    if pr.base_ref not in {"main", "refs/heads/main"}:
        return Decision("block", f"base branch is {pr.base_ref}")
    if required is None:
        return Decision(
            "block",
            "required checks could not be established; refusing to merge",
        )

    combined = combine_checks(list(pr.checks))
    missing = [name for name in required if name not in combined]
    pending = [
        combined[name]
        for name in required
        if name in combined and combined[name].conclusion in PENDING
    ]
    failed = [
        combined[name]
        for name in required
        if name in combined and combined[name].conclusion in FAILURES
    ]
    unacceptable = [
        combined[name]
        for name in required
        if name in combined and combined[name].conclusion in UNACCEPTABLE
    ]
    if failed:
        names = ", ".join(check.name for check in failed)
        return Decision("needs-fix", f"required checks failed: {names}", tuple(failed))
    if pending or missing:
        parts = []
        if pending:
            parts.append("pending: " + ", ".join(check.name for check in pending))
        if missing:
            parts.append("missing: " + ", ".join(missing))
        return Decision("wait", "; ".join(parts))
    if unacceptable:
        names = ", ".join(
            f"{check.name} ({check.conclusion})" for check in unacceptable
        )
        return Decision("block", f"required checks are not successful: {names}")

    if pr.mergeable == "UNKNOWN" or pr.merge_state == "UNKNOWN":
        return Decision("retry", "mergeability is unknown")
    if pr.mergeable == "CONFLICTING" or pr.merge_state == "DIRTY":
        return Decision("needs-rereview", "pull request conflicts with the base branch")
    if pr.merge_state == "UNSTABLE":
        return Decision(
            "block",
            "merge state is unstable even though classified checks passed",
        )
    if pr.merge_state == "HAS_HOOKS":
        return Decision("wait", "merge hooks are still running")

    if not _base_allows_merge(pr, binding, overlap):
        if overlap in {"overlap", "unknown"}:
            return Decision(
                "needs-rereview",
                "upstream moved and the change may invalidate the review",
            )
        return Decision(
            "needs-revalidation",
            "upstream moved without overlapping files; fresh integration validation is required",
        )

    if pr.merge_state == "BEHIND":
        return Decision(
            "needs-revalidation",
            "GitHub reports the branch behind base",
        )

    if pr.review_decision == "CHANGES_REQUESTED":
        return Decision("block", "reviewer requested changes")

    if admin_bypass_allowed(pr, binding, required, overlap=overlap):
        return Decision(
            "admin-merge",
            "human review approval is the only remaining blocker",
            use_admin=True,
        )

    if pr.merge_state == "CLEAN" and pr.review_decision in {"APPROVED", ""}:
        return Decision("merge", "required checks passed and the pull request is mergeable")

    if pr.merge_state == "BLOCKED":
        return Decision(
            "block",
            f"merge is blocked (review decision: {pr.review_decision or 'none'})",
        )

    return Decision("block", f"unrecognized merge state {pr.merge_state}")


def _required_all_success(pr: PrView, required: list[str]) -> bool:
    combined = combine_checks(list(pr.checks))
    if any(name not in combined for name in required):
        return False
    return all(combined[name].conclusion == "success" for name in required)


def _base_allows_merge(pr: PrView, binding: ReviewBinding, overlap: str) -> bool:
    if not binding.base_sha or pr.base_sha == binding.base_sha:
        return overlap in {"same-base", "disjoint"}
    if overlap == "disjoint" and (
        binding.integration_base_sha == pr.base_sha
        and binding.integration_result == "pass"
    ):
        return True
    return False

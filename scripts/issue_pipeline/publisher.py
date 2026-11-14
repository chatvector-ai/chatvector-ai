"""Deterministic submit and finalize. Merge runs inside a cross-process lock."""

from __future__ import annotations

from pathlib import Path

from .decisions import ReviewBinding, decide
from .github import (
    GitHubError,
    areas_from_paths,
    render_merge_message,
    render_pr_body,
)
from .locks import merge_lock
from .models import MERGED, MERGING, PENDING_CI, READY, IssueRecord, PublishError, transition
from .gitrepo import GitRepo, discover_main_checkout
from .revalidate import attempt_auto_revalidate, auto_revalidate_enabled
from .scheduler import apply_ci_decision, complete_merge
from .telemetry import ci_pending
from .state import StateStore


def submit(store: StateStore, git, hub, key: str) -> dict:
    issue = _ready_issue(store, key)
    worktree = Path(issue.worktree or "")
    if not issue.worktree or not issue.branch or not issue.base_sha or not issue.reviewed_sha:
        raise PublishError("branch, worktree, base SHA, and reviewed SHA are required")
    head = git.rev_parse(worktree)
    if head != issue.reviewed_sha:
        raise PublishError(f"HEAD {head} does not match reviewed SHA {issue.reviewed_sha}")
    if git.current_branch(worktree) != issue.branch:
        raise PublishError(
            f"worktree is on {git.current_branch(worktree)}, expected {issue.branch}"
        )
    if not git.status_clean(worktree):
        raise PublishError("worktree is not clean")

    repos = hub.resolve_repos()
    lease = issue.pushed_sha if issue.rebase_authorized and issue.pushed_sha else None
    git.push(worktree, "origin", issue.branch, force_with_lease_sha=lease)
    body = render_pr_body(issue)
    title = issue.title or f"Issue {issue.number}"
    changed = git.diff_names(issue.base_sha, head) or set()
    existing = None
    if issue.pr_number:
        existing = hub.get_pr(issue.pr_number)
        if existing.state != "OPEN":
            raise PublishError(f"pull request #{issue.pr_number} is {existing.state}")
    if existing is None:
        existing = hub.find_open_pr(repos.fork_owner, issue.branch)
    if existing is not None:
        pr = hub.update_pr(existing.number, title=title, body=body)
        created = False
    else:
        pr = hub.create_pr(branch=issue.branch, title=title, body=body)
        created = True
    if pr.head_sha and pr.head_sha != head:
        raise PublishError(
            f"pull request head {pr.head_sha} does not match reviewed SHA {head}"
        )

    with store.transaction() as state:
        current = state.issues[str(key)]
        if current.state != READY or current.reviewed_sha != head:
            raise PublishError("issue changed during submit; not marking it pending")
        transition(current, PENDING_CI)
        current.pr_number = pr.number
        current.pr_url = pr.url
        current.pushed_sha = head
        current.head_sha = head
        if lease:
            current.rebase_authorized = False
        current.areas = areas_from_paths(changed)
        current.reason_code = None
        current.notes = None
        state.event(current.key, "submitted", f"PR #{pr.number} {head}")
        ci_pending(state, current, f"PR #{pr.number}")
    return {
        "ok": True,
        "issue": str(key),
        "action": "pending-ci",
        "pr": pr.number,
        "url": pr.url,
        "created": created,
        "sha": head,
    }


def tick(
    store: StateStore,
    git,
    hub,
    *,
    lock_path: Path,
    suite_lock_path: Path | None = None,
    only: str | None = None,
) -> dict:
    with store.transaction() as state:
        if only is not None:
            keys = [str(only)]
        else:
            keys = [
                issue.key
                for issue in state.issues.values()
                if issue.state in {PENDING_CI, MERGING}
            ]
    auto = auto_revalidate_enabled() and suite_lock_path is not None
    results: list[dict] = []
    for key in keys:
        first = finalize_issue(store, git, hub, key, lock_path=lock_path)
        results.append(first)
        if not auto or first.get("action") != "needs-revalidation":
            continue
        attempt = attempt_auto_revalidate(
            store, git, hub, key, suite_lock_path=suite_lock_path
        )
        results.append(
            {
                "issue": str(key),
                "action": "auto-revalidate",
                **attempt,
            }
        )
        if attempt.get("recorded") and attempt.get("result") == "pass":
            results.append(finalize_issue(store, git, hub, key, lock_path=lock_path))
    return {"ok": True, "results": results, "auto_revalidate": auto}


def finalize_issue(store: StateStore, git, hub, key: str, *, lock_path: Path) -> dict:
    with store.transaction() as state:
        issue = state.issues[str(key)]
        if issue.state == MERGED:
            return _merged_payload(issue)
        if issue.state not in {PENDING_CI, MERGING} or not issue.pr_number:
            raise PublishError(f"{key} is not awaiting CI")

    inspected = _inspect(store, git, hub, key)
    decision = decide(
        inspected["pr"],
        inspected["binding"],
        inspected["required"],
        overlap=inspected["overlap"],
        independent_review=inspected["issue"].review_verdict,
    )
    if decision.action not in {"merge", "admin-merge", "already-merged"}:
        _apply(store, key, decision, inspected["local_sha"], inspected["pr"])
        return _decision_payload(key, decision, inspected["pr"])

    with merge_lock(lock_path):
        result = _merge_under_lock(store, git, hub, key)
    if result.get("action") == "merged":
        sync = _sync_primary(git, result.get("merge_sha") or "")
        result["sync"] = sync
        _record_primary_sync(store, key, sync)
    if result.get("action") == "merge-incomplete":
        result["sync"] = None
    return result


def _merge_under_lock(store: StateStore, git, hub, key: str) -> dict:
    inspected = _inspect(store, git, hub, key)
    decision = decide(
        inspected["pr"],
        inspected["binding"],
        inspected["required"],
        overlap=inspected["overlap"],
    )
    if decision.action == "already-merged":
        return _observe_merged(store, key, inspected["pr"])
    if decision.action not in {"merge", "admin-merge"}:
        _apply(store, key, decision, inspected["local_sha"], inspected["pr"])
        return _decision_payload(key, decision, inspected["pr"])
    _mark_merging(store, key)
    try:
        attempt, method = _merge_once(hub, git, store, key, inspected, decision)
    except GitHubError as exc:
        _abort_merge(store, key, str(exc))
        return {"ok": False, "issue": str(key), "action": "block", "reason": str(exc)}
    if attempt is None:
        inspected = _inspect(store, git, hub, key)
        decision = decide(
            inspected["pr"],
            inspected["binding"],
            inspected["required"],
            overlap=inspected["overlap"],
        )
        _apply(store, key, decision, inspected["local_sha"])
        return _decision_payload(key, decision, inspected["pr"])
    return _finish_merge(store, key, attempt, method)


def _sync_primary(git, merge_sha: str) -> dict:
    root = getattr(git, "root", None)
    if root is None:
        return {
            "status": "unavailable",
            "message": "git sync is not available",
            "merge_sha": merge_sha,
            "github_merge_success": True,
        }
    try:
        primary_git = GitRepo(discover_main_checkout(Path(root)))
        return primary_git.sync_primary_main(merge_sha=merge_sha)
    except Exception as exc:
        return {
            "status": "failed",
            "message": str(exc),
            "merge_sha": merge_sha,
            "github_merge_success": True,
        }


def _record_primary_sync(store: StateStore, key: str, sync: dict) -> None:
    with store.transaction() as state:
        issue = state.issues[str(key)]
        issue.primary_sync = sync
        status = sync.get("status") or "unknown"
        state.event(issue.key, "primary-sync", status)


def _merge_once(hub, git, store, key: str, inspected: dict, decision) -> tuple:
    issue = inspected["issue"]
    subject, body = render_merge_message(issue)
    sha = issue.reviewed_sha or ""
    if decision.action == "admin-merge":
        if not decision.use_admin:
            return None, ""
        refreshed = _inspect(store, git, hub, key)
        again = decide(
            refreshed["pr"],
            refreshed["binding"],
            refreshed["required"],
            overlap=refreshed["overlap"],
            independent_review=refreshed["issue"].review_verdict,
        )
        if again.action != "admin-merge" or not again.use_admin:
            return None, ""
        subject, body = render_merge_message(refreshed["issue"])
        attempt = hub.merge(
            refreshed["pr"].number,
            admin=True,
            sha=refreshed["issue"].reviewed_sha or "",
            subject=subject,
            body=body,
        )
        return attempt, "admin-review-bypass"

    if decision.action == "merge":
        attempt = hub.merge(
            inspected["pr"].number,
            admin=False,
            sha=sha,
            subject=subject,
            body=body,
        )
        return attempt, "squash"

    return None, ""


def _inspect(store: StateStore, git, hub, key: str) -> dict:
    with store.transaction() as state:
        issue = state.issues[str(key)]
        snapshot = IssueRecord.from_dict(issue.to_dict())
    if not snapshot.pr_number or not snapshot.reviewed_sha:
        raise PublishError(f"{key} has no pull request or reviewed SHA")
    pr = hub.get_pr(snapshot.pr_number)
    required = hub.required_checks()
    local_sha = None
    if snapshot.worktree:
        local_sha = git.rev_parse(Path(snapshot.worktree))
    overlap = "same-base"
    if snapshot.base_sha and pr.base_sha and pr.base_sha != snapshot.base_sha:
        upstream_files = git.diff_names(snapshot.base_sha, pr.base_sha)
        pr_files = git.diff_names(snapshot.base_sha, snapshot.reviewed_sha)
        if upstream_files is None or pr_files is None:
            overlap = "unknown"
        elif upstream_files & pr_files:
            overlap = "overlap"
        else:
            overlap = "disjoint"
    binding = ReviewBinding(
        reviewed_sha=snapshot.reviewed_sha,
        base_sha=snapshot.base_sha,
        integration_base_sha=snapshot.integration_base_sha,
        integration_result=snapshot.integration_result,
    )
    return {
        "issue": snapshot,
        "pr": pr,
        "required": required,
        "overlap": overlap,
        "local_sha": local_sha,
        "binding": binding,
    }


def _ready_issue(store: StateStore, key: str) -> IssueRecord:
    with store.transaction() as state:
        issue = state.issues[str(key)]
        if issue.state != READY or issue.review_verdict != "READY" or not issue.reviewed_sha:
            raise PublishError(f"{key} is not a READY review")
        return IssueRecord.from_dict(issue.to_dict())


def _apply(store: StateStore, key: str, decision, local_sha: str | None, pr) -> None:
    with store.transaction() as state:
        issue = state.issues[str(key)]
        if issue.state == MERGING and decision.action != "already-merged":
            transition(issue, PENDING_CI)
        apply_ci_decision(state, issue, decision, local_sha=local_sha)
        if decision.action == "needs-revalidation":
            issue.upstream_base_sha = pr.base_sha


def _mark_merging(store: StateStore, key: str) -> None:
    with store.transaction() as state:
        issue = state.issues[str(key)]
        if issue.state == PENDING_CI:
            transition(issue, MERGING)
        elif issue.state != MERGING:
            raise PublishError(f"{key} left the CI queue before merge")
        state.event(issue.key, "merging", issue.reviewed_sha or "")


def _abort_merge(store: StateStore, key: str, reason: str) -> None:
    with store.transaction() as state:
        issue = state.issues[str(key)]
        if issue.state == MERGING:
            transition(issue, PENDING_CI)
        issue.notes = reason
        state.event(issue.key, "merge-aborted", reason[:500])


def _finish_merge(store: StateStore, key: str, attempt, method: str) -> dict:
    if not attempt.completed or not attempt.merge_sha:
        _abort_merge(store, key, "merge command finished before the pull request was merged")
        return {
            "ok": False,
            "issue": str(key),
            "action": "wait",
            "reason": "merge did not complete",
        }
    with store.transaction() as state:
        issue = state.issues[str(key)]
        complete_merge(state, issue, attempt.merge_sha, method)
        payload = _merged_payload(issue)
    return payload


def _observe_merged(store: StateStore, key: str, pr) -> dict:
    if not pr.merge_sha:
        with store.transaction() as state:
            issue = state.issues[str(key)]
            if issue.state == MERGING:
                transition(issue, PENDING_CI)
            issue.notes = "PR already merged but merge SHA could not be verified"
            state.event(issue.key, "merge-incomplete", f"PR #{pr.number}")
        return {
            "ok": False,
            "issue": str(key),
            "action": "merge-incomplete",
            "pr": pr.number,
            "reason": "merged pull request has no merge commit SHA",
        }
    with store.transaction() as state:
        issue = state.issues[str(key)]
        complete_merge(state, issue, pr.merge_sha, "observed")
        return _merged_payload(issue)


def _merged_payload(issue: IssueRecord) -> dict:
    return {
        "ok": True,
        "issue": issue.key,
        "action": "merged",
        "pr": issue.pr_number,
        "merge_sha": issue.merge_sha,
        "merge_method": issue.merge_method,
    }


def _decision_payload(key: str, decision, pr) -> dict:
    return {
        "ok": decision.action
        in {
            "wait",
            "retry",
            "needs-revalidation",
            "needs-integration-review",
            "needs-rereview",
        },
        "issue": str(key),
        "action": decision.action,
        "reason": decision.reason,
        "pr": pr.number,
        "use_admin": decision.use_admin,
        "base_sha": pr.base_sha,
        "head_sha": pr.head_sha,
        "failed_checks": [
            {"name": check.name, "url": check.url, "conclusion": check.conclusion}
            for check in decision.failed_checks
        ],
    }

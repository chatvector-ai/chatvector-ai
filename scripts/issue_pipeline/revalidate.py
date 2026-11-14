"""Automatic integration revalidation while a pull request waits on pending-ci."""

from __future__ import annotations

import os
import shlex
from pathlib import Path

from .locks import command_needs_lock, run_verified
from .migration_guard import assert_migration_ledger_compatible
from .models import PENDING_CI, PublishError
from .scheduler import record_integration
from .state import StateStore


def auto_revalidate_enabled() -> bool:
    value = os.environ.get("PIPELINE_AUTO_REVALIDATE", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def default_revalidate_command() -> list[str]:
    raw = os.environ.get("PIPELINE_REVALIDATE_PYTEST", "").strip()
    if raw:
        return shlex.split(raw)
    return ["pytest", "backend/tests/", "-q", "--tb=short"]


def attempt_auto_revalidate(
    store: StateStore,
    git,
    hub,
    key: str,
    *,
    suite_lock_path: Path,
) -> dict:
    """Run locked pytest in the issue worktree and record integration when required."""

    with store.transaction() as state:
        issue = state.issues[str(key)]
        if issue.state != PENDING_CI or issue.reason_code != "needs-revalidation":
            return {
                "ok": True,
                "skipped": True,
                "reason": "not awaiting integration revalidation",
            }
        if not issue.worktree or not issue.reviewed_sha:
            return {"ok": False, "skipped": True, "reason": "missing worktree or reviewed SHA"}
        worktree = Path(issue.worktree)
        reviewed_sha = issue.reviewed_sha
        pr_number = issue.pr_number
        snapshot_base = issue.upstream_base_sha

    if not worktree.is_dir():
        return {"ok": False, "skipped": True, "reason": f"worktree missing: {worktree}"}

    head = git.rev_parse(worktree)
    if head != reviewed_sha:
        return {
            "ok": False,
            "skipped": True,
            "reason": f"worktree HEAD {head} does not match reviewed {reviewed_sha}",
        }
    if not git.status_clean(worktree):
        return {"ok": False, "skipped": True, "reason": "worktree is not clean"}

    base_sha = snapshot_base
    if not base_sha and pr_number:
        base_sha = hub.get_pr(pr_number).base_sha
    if not base_sha:
        return {"ok": False, "skipped": True, "reason": "upstream base SHA is unknown"}

    command = default_revalidate_command()
    if command_needs_lock(command):
        assert_migration_ledger_compatible(worktree)
    exit_code, locked = run_verified(suite_lock_path, command, cwd=worktree)
    result = "pass" if exit_code == 0 else "fail"

    try:
        with store.transaction() as state:
            record_integration(
                state,
                str(key),
                base_sha,
                result,
                head_sha=head,
                clean=True,
            )
            current = state.issues[str(key)]
    except PublishError as exc:
        return {
            "ok": False,
            "recorded": False,
            "reason": str(exc),
            "verify_exit_code": exit_code,
            "locked": locked,
        }

    return {
        "ok": result == "pass",
        "recorded": True,
        "result": result,
        "base_sha": base_sha,
        "verify_exit_code": exit_code,
        "locked": locked,
        "issue_state": current.state,
        "reason_code": current.reason_code,
    }

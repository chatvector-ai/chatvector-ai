from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from scripts.issue_pipeline.github import MergeAttempt
from scripts.issue_pipeline.models import BatchState, IssueRecord, PENDING_CI
from scripts.issue_pipeline.publisher import tick
from scripts.issue_pipeline.state import StateStore

from .test_publisher import BASE, FakeGit, FakeHub, _open_pr

MAIN_ADVANCED = "c" * 40
SHA = "d" * 40
MERGE_SHA = "f" * 40


class HexMergeHub(FakeHub):
    def merge(self, number, *, admin, sha, subject, body):
        with self._lock:
            current = self.prs[number]
            merged = replace(current, state="MERGED", merge_sha=MERGE_SHA)
            self.prs[number] = merged
            self.merges.append(
                {"number": number, "admin": admin, "sha": sha, "subject": subject, "body": body}
            )
        return MergeAttempt(True, MERGE_SHA, "", "")


def _pending_issue(worktree: Path) -> IssueRecord:
    return IssueRecord(
        key="674",
        number=674,
        title="Issue 674",
        summary="Issue 674",
        state=PENDING_CI,
        review_verdict="READY",
        reviewed_sha=SHA,
        base_sha=BASE,
        head_sha=SHA,
        branch="feature/674",
        worktree=str(worktree),
        pr_number=674,
        reason_code="needs-revalidation",
        upstream_base_sha=MAIN_ADVANCED,
        findings="none",
        verification="scripts/issue-pipeline verify -- pytest backend/tests/ -q",
    )


@patch("scripts.issue_pipeline.revalidate.run_verified", return_value=(0, True))
def test_tick_auto_revalidates_then_merges(mock_run_verified, tmp_path):
    worktree = tmp_path / "wt674"
    worktree.mkdir()
    state = BatchState(concurrency=1)
    state.issues["674"] = _pending_issue(worktree)
    store = StateStore(tmp_path / "state.json")
    store.save(state)

    hub = HexMergeHub()
    hub.prs[674] = _open_pr(674, head=SHA, base=MAIN_ADVANCED)
    git = FakeGit(head=SHA, clean=True)
    lock = tmp_path / "merge.lock"
    suite_lock = tmp_path / "suite.lock"

    payload = tick(
        store,
        git,
        hub,
        lock_path=lock,
        suite_lock_path=suite_lock,
    )
    assert payload["auto_revalidate"] is True
    actions = [item["action"] for item in payload["results"]]
    assert "needs-revalidation" in actions
    assert "auto-revalidate" in actions
    assert "merged" in actions
    mock_run_verified.assert_called_once()

    saved = store.load().issues["674"]
    assert saved.state == "merged"
    assert saved.integration_result == "pass"
    assert saved.integration_base_sha == MAIN_ADVANCED


@patch("scripts.issue_pipeline.revalidate.run_verified", return_value=(0, True))
def test_tick_skips_auto_revalidate_when_disabled(mock_run_verified, tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_AUTO_REVALIDATE", "0")
    worktree = tmp_path / "wt674"
    worktree.mkdir()
    state = BatchState(concurrency=1)
    state.issues["674"] = _pending_issue(worktree)
    store = StateStore(tmp_path / "state.json")
    store.save(state)

    hub = FakeHub()
    hub.prs[674] = _open_pr(674, head=SHA, base=MAIN_ADVANCED)
    git = FakeGit(head=SHA, clean=True)

    payload = tick(
        store,
        git,
        hub,
        lock_path=tmp_path / "merge.lock",
        suite_lock_path=tmp_path / "suite.lock",
    )
    assert payload["auto_revalidate"] is False
    assert all(item.get("action") != "auto-revalidate" for item in payload["results"])
    mock_run_verified.assert_not_called()
    assert store.load().issues["674"].reason_code == "needs-revalidation"


@patch("scripts.issue_pipeline.revalidate.run_verified", return_value=(1, True))
def test_tick_auto_revalidate_failure_becomes_needs_fix(mock_run_verified, tmp_path):
    worktree = tmp_path / "wt674"
    worktree.mkdir()
    state = BatchState(concurrency=1)
    state.issues["674"] = _pending_issue(worktree)
    store = StateStore(tmp_path / "state.json")
    store.save(state)

    hub = FakeHub()
    hub.prs[674] = _open_pr(674, head=SHA, base=MAIN_ADVANCED)
    git = FakeGit(head=SHA, clean=True)

    payload = tick(
        store,
        git,
        hub,
        lock_path=tmp_path / "merge.lock",
        suite_lock_path=tmp_path / "suite.lock",
    )
    reval = next(item for item in payload["results"] if item.get("action") == "auto-revalidate")
    assert reval["result"] == "fail"
    saved = store.load().issues["674"]
    assert saved.state == "needs-fix"

"""Tests for poll-ci and needs-rereview handling."""

from __future__ import annotations

from scripts.issue_pipeline.decisions import ReviewBinding, decide
from scripts.issue_pipeline.models import NEEDS_FIX, PENDING_CI, IssueRecord
from scripts.issue_pipeline.poll_ci import poll_ci
from scripts.issue_pipeline.scheduler import apply_ci_decision
from scripts.issue_pipeline.state import StateStore

from .test_publisher import BASE, FakeGit, FakeHub, _open_pr


def test_needs_rereview_overlap_routes_to_review_only(tmp_path):
    store = StateStore(tmp_path / "state.json")
    with store.transaction() as state:
        state.issues["652"] = IssueRecord(
            key="652",
            number=652,
            title="t",
            summary="t",
            state=PENDING_CI,
            review_verdict="READY",
            reviewed_sha="b" * 40,
            base_sha=BASE,
            head_sha="b" * 40,
            pr_number=652,
        )
    with store.transaction() as state:
        apply_ci_decision(
            state,
            state.issues["652"],
            decide(
                _open_pr(652, head="b" * 40, base="c" * 40),
                ReviewBinding(reviewed_sha="b" * 40, base_sha=BASE),
                ["Backend Tests"],
                overlap="overlap",
                independent_review="READY",
            ),
            local_sha="b" * 40,
        )
    saved = store.load().issues["652"]
    assert saved.state == NEEDS_FIX
    assert saved.correction_kind == "review-only"
    assert saved.fix_round == 0


def test_poll_ci_returns_immediately_when_nothing_pending(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state.json")
    hub = FakeHub()
    git = FakeGit()
    calls = {"n": 0}

    def fake_sleep(_seconds):
        calls["n"] += 1

    monkeypatch.setattr("scripts.issue_pipeline.poll_ci.time.sleep", fake_sleep)
    result = poll_ci(
        store,
        git,
        hub,
        lock_path=tmp_path / "merge.lock",
        suite_lock_path=tmp_path / "suite.lock",
        interval=0.01,
        max_wait=5.0,
    )
    assert result["done"] is True
    assert result["reason"] == "no pending-ci pull requests"
    assert calls["n"] == 0
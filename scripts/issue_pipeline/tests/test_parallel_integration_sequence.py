"""Regression: parallel batch 653 → 652 → 654 with simulated sibling merges."""

from __future__ import annotations

from dataclasses import replace

from scripts.issue_pipeline.decisions import ReviewBinding, decide
from scripts.issue_pipeline.models import NEEDS_FIX, PENDING_CI, READY, BatchState, IssueRecord
from scripts.issue_pipeline.publisher import finalize_issue
from scripts.issue_pipeline.scheduler import apply_ci_decision, record_integration
from scripts.issue_pipeline.state import StateStore

from .test_publisher import BASE, FakeGit, FakeHub, _open_pr

MAIN_ADVANCED = "c" * 40
SHA653 = "a" * 40
SHA652 = "b" * 40
SHA654 = "d" * 40


class OverlapGit(FakeGit):
    """Simulate file-level overlap between upstream advances and PR branches."""

    def diff_names(self, base, head):
        if head == SHA653:
            return {"backend/a.py"}
        if head == SHA652:
            return {"backend/a.py", "frontend/x.tsx"}
        if head == SHA654:
            return {"backend/shared.py", "backend/b.py"}
        if base == BASE and head == MAIN_ADVANCED:
            return {"backend/a.py"}
        if base == MAIN_ADVANCED and head == "e" * 40:
            return {"backend/shared.py", "frontend/x.tsx"}
        return set()


def _seed_batch(tmp_path) -> StateStore:
    state = BatchState(concurrency=3)
    for key, number, reviewed in (
        ("653", 653, SHA653),
        ("652", 652, SHA652),
        ("654", 654, SHA654),
    ):
        state.issues[key] = IssueRecord(
            key=key,
            number=number,
            title=f"Issue {number}",
            summary=f"Issue {number}",
            state=PENDING_CI,
            review_verdict="READY",
            reviewed_sha=reviewed,
            base_sha=BASE,
            head_sha=reviewed,
            branch=f"feature/{number}",
            worktree=str(tmp_path / f"wt{number}"),
            pr_number=number,
            findings="none",
            verification="scripts/issue-pipeline verify -- pytest backend/tests -q",
        )
    store = StateStore(tmp_path / "state.json")
    store.save(state)
    return store


def test_merge_sequence_653_then_652_then_654(tmp_path):
    store = _seed_batch(tmp_path)
    hub = FakeHub()
    hub.prs[653] = _open_pr(653, head=SHA653, base=BASE)
    hub.prs[652] = _open_pr(652, head=SHA652, base=BASE)
    hub.prs[654] = _open_pr(654, head=SHA654, base=BASE)
    lock = tmp_path / "merge.lock"
    git = OverlapGit()

    first = finalize_issue(store, git, hub, "653", lock_path=lock)
    assert first["action"] == "merged"

    overlap_652 = finalize_issue(store, git, hub, "652", lock_path=lock)
    assert overlap_652["action"] == "needs-integration-review"
    issue652 = store.load().issues["652"]
    assert issue652.state == NEEDS_FIX
    assert issue652.correction_kind == "review-only"
    assert issue652.reviewed_sha == SHA652
    assert issue652.fix_round == 0

    disjoint_654 = finalize_issue(store, git, hub, "654", lock_path=lock)
    assert disjoint_654["action"] == "needs-revalidation"
    assert store.load().issues["654"].fix_round == 0

    with store.transaction() as state:
        record_integration(state, "654", MAIN_ADVANCED, "pass", head_sha=SHA654, clean=True)
        state.issues["654"].review_verdict = "READY"

    second_base = "e" * 40
    hub.prs[652] = _open_pr(652, head=SHA652, base=MAIN_ADVANCED)
    with store.transaction() as state:
        record_integration(state, "652", MAIN_ADVANCED, "pass", head_sha=SHA652, clean=True)
        state.issues["652"].review_verdict = "READY"
        state.issues["652"].state = READY

    merged_652 = finalize_issue(store, git, hub, "652", lock_path=lock)
    assert merged_652["action"] == "merged"

    hub.prs[654] = _open_pr(654, head=SHA654, base=second_base)
    overlap_654 = finalize_issue(store, git, hub, "654", lock_path=lock)
    assert overlap_654["action"] == "needs-integration-review"
    assert store.load().issues["654"].correction_kind == "review-only"
    assert store.load().issues["654"].fix_round == 0


def test_disjoint_revalidation_does_not_consume_fix_round(tmp_path):
    store = _seed_batch(tmp_path)
    with store.transaction() as state:
        apply_ci_decision(
            state,
            state.issues["654"],
            decide(
                _open_pr(654, head=SHA654, base=MAIN_ADVANCED),
                ReviewBinding(reviewed_sha=SHA654, base_sha=BASE),
                ["Backend Tests"],
                overlap="disjoint",
                independent_review="READY",
            ),
            local_sha=SHA654,
        )
    saved = store.load().issues["654"]
    assert saved.reason_code == "needs-revalidation"
    assert saved.fix_round == 0
    assert saved.state == PENDING_CI

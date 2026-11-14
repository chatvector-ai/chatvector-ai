import os
from pathlib import Path

from scripts.issue_pipeline.models import (
    BLOCKED,
    IMPLEMENTING,
    MERGED,
    NEEDS_FIX,
    PENDING_CI,
    QUEUED,
    READY,
    REVIEWING,
    TransitionError,
    transition,
)
from scripts.issue_pipeline.scheduler import (
    apply_implement_handoff,
    apply_review_handoff,
    claim,
    complete_merge,
    next_actions,
    reconcile,
)
from scripts.issue_pipeline.state import StateStore

from support import plan, snapshot


def _ready_impl(state, key, sha="abc123def4567890"):
    claim(state, key, "implement", pid=0)
    apply_implement_handoff(
        state,
        key,
        {
            "Status": "ready-for-review",
            "Tasks": "all",
            "SHA": sha,
            "Base-SHA": state.issues[key].base_sha or sha,
            "Verification": "pytest passed",
        },
        head_sha=sha,
        clean=True,
    )


def test_user_scenario_starts_independent_issues_and_holds_dependents():
    state = plan(
        "1\n2\n3\n4\n5\n",
        [
            snapshot(1),
            snapshot(2),
            snapshot(3, body="Depends on #2"),
            snapshot(4, body="Depends on #3"),
            snapshot(5),
        ],
    )
    first = [item["issue"] for item in next_actions(state)["actions"]]
    assert first == ["1", "2", "5"]
    transition(state.issues["2"], MERGED)
    for key in ("1", "5"):
        claim(state, key, "implement", pid=os.getpid())
    nxt = next_actions(state)
    assert [item["issue"] for item in nxt["actions"]] == ["3"]
    transition(state.issues["3"], MERGED)
    # #1 and #5 still hold two slots, so #4 fills the remaining slot.
    assert [item["issue"] for item in next_actions(state)["actions"]] == ["4"]


def test_concurrency_limit_and_claimed_work_is_not_relaunched():
    state = plan("Concurrency: 2\n1\n2\n3\n", [snapshot(n) for n in (1, 2, 3)])
    claim(state, "1", "implement", pid=0)
    claim(state, "2", "implement", pid=0)
    try:
        claim(state, "3", "implement", pid=0)
    except TransitionError as exc:
        assert "concurrency" in str(exc)
    else:
        raise AssertionError("third claim was allowed")
    assert next_actions(state)["actions"] == []
    assert next_actions(state)["slots_used"] == 2


def test_sequential_mode_waits_for_ci_and_parallel_mode_does_not():
    sequential = plan("Concurrency: 1\n1\n2\n", [snapshot(1), snapshot(2)])
    sequential.issues["1"].state = PENDING_CI
    sequential.issues["1"].pr_number = 10
    assert next_actions(sequential)["actions"] == []

    parallel = plan("1\n2\n", [snapshot(1), snapshot(2)])
    parallel.issues["1"].state = PENDING_CI
    parallel.issues["1"].pr_number = 10
    assert [item["issue"] for item in next_actions(parallel)["actions"]] == ["2"]


def test_ready_issue_is_published_without_consuming_a_parallel_slot():
    state = plan("1\n2\n3\n4\n", [snapshot(n) for n in range(1, 5)])
    state.issues["1"].base_sha = "base"
    _ready_impl(state, "1", "abc123def4567890")
    claim(state, "1", "review", pid=0)
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "READY",
            "Reviewed-SHA": "abc123def4567890",
            "Base-SHA": "base",
            "Tasks-checked": "2/2",
            "Pytest": "passed 10",
            "Verification": "pytest passed",
            "Findings": "none",
        },
        head_sha="abc123def4567890",
    )
    assert state.issues["1"].state == READY
    report = next_actions(state)
    assert report["publish"][0]["issue"] == "1"
    assert report["slots_used"] == 0
    assert len(report["actions"]) == 3


def test_review_fix_and_fix_limit():
    state = plan("Max fix rounds: 2\n1\n", [snapshot(1)])
    state.issues["1"].base_sha = "base"
    _ready_impl(state, "1")
    claim(state, "1", "review", pid=0)
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "FIX FIRST",
            "Reviewed-SHA": "abc123def4567890",
            "Findings": "null check missing",
        },
        head_sha="abc123def4567890",
    )
    assert state.issues["1"].state == NEEDS_FIX
    assert state.issues["1"].reviewed_sha is None
    claim(state, "1", "implement", pid=0)
    assert state.issues["1"].fix_round == 1
    state.issues["1"].fix_round = 2
    state.issues["1"].state = REVIEWING
    state.issues["1"].claimed = False
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "NOT CLOSE",
            "Reviewed-SHA": "abc123def4567890",
            "Findings": "still broken",
        },
        head_sha="abc123def4567890",
    )
    assert state.issues["1"].state == BLOCKED
    assert state.issues["1"].reason_code == "fix-limit"


def test_malformed_review_retries_once_then_blocks():
    state = plan("1\n", [snapshot(1)])
    state.issues["1"].state = REVIEWING
    state.issues["1"].base_sha = "base"
    apply_review_handoff(
        state,
        "1",
        {"Verdict": "READY", "Reviewed-SHA": "different", "Pytest": "passed", "Tasks-checked": "1/1", "Verification": "x", "Base-SHA": "base"},
        head_sha="abc123def4567890",
    )
    assert state.issues["1"].state == REVIEWING
    apply_review_handoff(
        state,
        "1",
        {"Verdict": "READY", "Reviewed-SHA": "different", "Pytest": "passed", "Tasks-checked": "1/1", "Verification": "x", "Base-SHA": "base"},
        head_sha="abc123def4567890",
    )
    assert state.issues["1"].state == BLOCKED
    assert state.issues["1"].reason_code == "review-malformed"


def test_ready_review_rejects_failed_tests_and_partial_tasks():
    state = plan("1\n", [snapshot(1)])
    state.issues["1"].state = REVIEWING
    state.issues["1"].base_sha = "base"
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "READY",
            "Reviewed-SHA": "abc123def4567890",
            "Base-SHA": "base",
            "Pytest": "failed: 1",
            "Tasks-checked": "1/1",
            "Verification": "pytest",
        },
        head_sha="abc123def4567890",
    )
    assert state.issues["1"].state == REVIEWING
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "READY",
            "Reviewed-SHA": "abc123def4567890",
            "Base-SHA": "base",
            "Pytest": "passed",
            "Tasks-checked": "1/2",
            "Verification": "pytest",
        },
        head_sha="abc123def4567890",
    )
    assert state.issues["1"].review_malformed == 2
    assert state.issues["1"].state == BLOCKED


def test_resume_requeues_an_abandoned_claim_without_duplicating_a_merged_pr():
    state = plan("1\n2\n", [snapshot(1), snapshot(2)])
    claim(state, "1", "implement", pid=0)
    state.issues["2"].state = "merging"
    state.issues["2"].pr_number = 40

    class Pr:
        state = "MERGED"
        number = 40
        merge_sha = "deadbeef"

    notes = reconcile(state, pr_for=lambda issue: Pr() if issue.pr_number == 40 else None)
    assert state.issues["1"].claimed is False
    assert state.issues["1"].interrupted is True
    assert state.issues["1"].state == IMPLEMENTING
    assert [item["action"] for item in next_actions(state)["actions"] if item["issue"] == "1"] == ["implement"]
    assert state.issues["2"].state == MERGED
    assert state.issues["2"].merge_sha == "deadbeef"
    assert any("observed merged" in note for note in notes)


def test_interrupted_merge_returns_to_pending_ci():
    state = plan("1\n", [snapshot(1)])
    state.issues["1"].state = "merging"
    state.issues["1"].pr_number = 9

    class Pr:
        state = "OPEN"
        number = 9
        merge_sha = None

    reconcile(state, pr_for=lambda issue: Pr())
    assert state.issues["1"].state == PENDING_CI


def test_state_survives_a_crash_mid_transaction_and_serializes_writers(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.save(plan("1\n", [snapshot(1)]))
    try:
        with store.transaction() as state:
            state.issues["1"].notes = "should roll back"
            raise RuntimeError("crash")
    except RuntimeError:
        pass
    assert store.load().issues["1"].notes is None

    import threading

    def bump():
        for _ in range(25):
            with store.transaction() as state:
                state.event("1", "bump")

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(store.load().events) == 100


def test_illegal_transition_is_rejected():
    state = plan("1\n", [snapshot(1)])
    try:
        transition(state.issues["1"], READY)
    except TransitionError:
        return
    raise AssertionError("queued issue moved directly to ready-to-publish")


def test_blocked_issue_does_not_stop_unrelated_work():
    state = plan("1\n2\n", [snapshot(1), snapshot(2, body="Depends on #9")])
    assert state.issues["2"].state == BLOCKED
    assert [item["issue"] for item in next_actions(state)["actions"]] == ["1"]


def test_complete_merge_releases_a_cascade_blocked_dependent():
    state = plan(
        "1\n2\n3\n",
        [snapshot(1), snapshot(2, body="Depends on #1"), snapshot(3, body="Depends on #9")],
    )
    # #2 is queued behind #1. Block #1 and cascade #2, then merge #1 through the real helper.
    state.issues["1"].state = PENDING_CI
    state.issues["1"].pr_number = 3
    from scripts.issue_pipeline.scheduler import block_issue

    block_issue(state, "1", "operator stop")
    assert state.issues["2"].reason_code == "blocked-prerequisite"
    # A blocked issue cannot merge. Put #1 back on the CI path and complete it.
    state.issues["1"].state = PENDING_CI
    state.issues["1"].reason_code = None
    complete_merge(state, state.issues["1"], "abc", "squash")
    assert state.issues["1"].state == MERGED
    assert state.issues["2"].state == QUEUED
    assert state.issues["3"].state == BLOCKED

from scripts.issue_pipeline.dependencies import GraphError, is_epic
from scripts.issue_pipeline.models import BLOCKED, MERGED, QUEUED
from scripts.issue_pipeline.queue import parse_queue

from .support import plan, snapshot


def test_independent_issues_are_all_runnable():
    state = plan("1\n2\n5\n", [snapshot(1), snapshot(2), snapshot(5)])
    assert state.concurrency == 3
    assert [issue.key for issue in state.issues.values() if issue.state == QUEUED] == ["1", "2", "5"]


def test_explicit_dependencies_and_blocked_by_links():
    state = plan(
        "1\n2\n3\n4\n5\n",
        [
            snapshot(1),
            snapshot(2),
            snapshot(3, body="Depends on #2 and #9"),
            snapshot(4, body="Blocked by #3"),
            snapshot(5, blocked_by=[1]),
        ],
    )
    assert state.issues["3"].hard_dependencies == ["2", "9"]
    assert state.issues["4"].hard_dependencies == ["3"]
    assert state.issues["5"].hard_dependencies == ["1"]
    assert state.issues["3"].state == BLOCKED
    assert state.issues["3"].reason_code == "missing-prerequisite"
    assert state.issues["4"].reason_code == "blocked-prerequisite"


def test_queue_annotation_is_a_hard_dependency():
    state = plan("2\n3 (after 2)\n", [snapshot(2), snapshot(3)])
    assert state.issues["3"].hard_dependencies == ["2"]


def test_cycle_is_rejected_and_self_dependency_is_rejected():
    try:
        plan("1\n2\n", [snapshot(1, body="Depends on #2"), snapshot(2, body="Depends on #1")])
    except GraphError as exc:
        assert "cyclic" in str(exc)
    else:
        raise AssertionError("cycle was accepted")
    try:
        plan("1\n", [snapshot(1, body="Depends on #1")])
    except GraphError as exc:
        assert "itself" in str(exc)
    else:
        raise AssertionError("self dependency was accepted")


def test_duplicate_issue_is_rejected():
    try:
        plan("1\n1\n", [snapshot(1)])
    except GraphError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate was accepted")


def test_closed_prerequisite_allows_the_dependent_to_queue():
    state = plan(
        "4\n",
        [snapshot(4, body="Depends on #2"), snapshot(2, closed=True)],
    )
    assert state.issues["2"].state == MERGED
    assert state.issues["2"].external is True
    assert state.issues["4"].state == QUEUED


def test_related_text_and_same_subsystem_are_not_dependencies():
    state = plan(
        "1\n2\n",
        [
            snapshot(1, body="Related to #2\n\nTouch the backend service."),
            snapshot(2, body="See also the backend service, related to #1."),
        ],
    )
    assert state.issues["1"].hard_dependencies == []
    assert state.issues["2"].hard_dependencies == []
    assert state.issues["1"].soft_conflicts == []


def test_shared_key_file_is_a_soft_conflict_only():
    body_one = "## Key files\n- `backend/api/items.py`\n"
    body_two = "## Key files\n- `backend/api/items.py`\nMay conflict with #1\n"
    state = plan("1\n2\n", [snapshot(1, body=body_one), snapshot(2, body=body_two)])
    assert state.issues["1"].hard_dependencies == []
    assert state.issues["1"].soft_conflicts == ["2"]
    assert state.issues["2"].soft_conflicts == ["1"]


def test_epic_batch_order_is_a_hard_chain_and_plain_children_are_not():
    ordered = """
## Child issues
- #10
- #11
## Batch order
#10 then #11
Tracking epic. Do not implement this issue.
"""
    loose = """
## Child issues
- #20
- #21
Tracking epic. Implementation lives in the child issues.
"""
    ordered_state = plan(
        "9\n",
        [snapshot(9, body=ordered), snapshot(10), snapshot(11)],
    )
    assert "9" not in ordered_state.issues
    assert ordered_state.issues["11"].hard_dependencies == ["10"]
    loose_state = plan(
        "19\n",
        [snapshot(19, body=loose), snapshot(20), snapshot(21)],
    )
    assert loose_state.issues["21"].hard_dependencies == []


def test_epic_queue_dependency_applies_to_every_child():
    body = """
## Child issues
- #10
Tracking epic. Do not implement this issue.
Depends on #8
"""
    state = plan("8\n9 (after 8)\n", [snapshot(8), snapshot(9, body=body), snapshot(10)])
    assert "8" in state.issues["10"].hard_dependencies


def test_no_expand_keeps_the_parent():
    body = "## Child issues\n- #10\nTracking epic. Do not implement.\n"
    state = plan("9 no-expand\n", [snapshot(9, body=body), snapshot(10)])
    assert "9" in state.issues
    assert "10" not in state.issues


def test_task_list_prevents_epic_expansion_without_tracking_language():
    body = "## Child issues\n- #10\n\n## Tasks\n- [ ] do the work\n"
    assert is_epic(body) is False


def test_labels_do_not_select_a_model_and_prefixes_do():
    state = plan(
        "1\ngrok:2\n",
        [snapshot(1, labels=["advanced", "security"]), snapshot(2, labels=["beginner"])],
    )
    assert state.issues["1"].model_slug is None
    assert state.issues["2"].model_slug == "grok-4.7-high"


def test_worker_mix_positions_follow_the_expanded_queue():
    text = "Worker mix: balanced\nAlternate slug: gpt-5.6-sol-medium\n1\n2\n"
    state = plan(text, [snapshot(1), snapshot(2)])
    assert state.issues["1"].model_slug is None
    assert state.issues["2"].model_slug == "gpt-5.6-sol-medium"
    explicit = plan(
        "Worker mix: other-heavy\nAlternate slug: gpt-5.6-sol-medium\nsonnet:1\n",
        [snapshot(1)],
    )
    assert explicit.issues["1"].model_slug == "claude-sonnet-5-5-high"


def test_concurrency_header_environment_and_sequential_fallback():
    assert plan("Concurrency: 1\n1\n", [snapshot(1)]).concurrency == 1
    forced = plan("Concurrency: 3\n1\n", [snapshot(1)], env={"PIPELINE_FORCE_SEQUENTIAL": "1"})
    assert forced.concurrency == 1
    assert forced.fallback == "sequential"
    from_env = plan("1\n", [snapshot(1)], env={"PIPELINE_MAX_ACTIVE": "2"})
    assert from_env.concurrency == 2
    try:
        parse_queue("Concurrency: 0\n1\n", {})
    except GraphError as exc:
        assert "Concurrency" in str(exc)
    else:
        raise AssertionError("zero concurrency was accepted")

import json
from pathlib import Path

import pytest

from scripts.issue_pipeline.findings import validate_actionable_findings
from scripts.issue_pipeline.models import REVIEWING, BatchState, IssueRecord
from scripts.issue_pipeline.scheduler import apply_review_handoff
from scripts.issue_pipeline.state import StateStore

from .support import plan, snapshot


def test_validate_rejects_verdict_only_findings():
    assert validate_actionable_findings("FIX FIRST", verdict="FIX FIRST")
    assert validate_actionable_findings("", verdict="NOT CLOSE")


def test_malformed_fix_first_does_not_mutate_history_or_fix_round():
    state = plan("1\n", [snapshot(1)])
    issue = state.issues["1"]
    issue.base_sha = "abc123def4567890"
    issue.state = REVIEWING
    issue.fix_round = 1
    issue.findings = "- prior finding"
    issue.last_review_findings = "- prior finding"
    before_history = len(issue.review_history)
    apply_review_handoff(
        state,
        "1",
        {
            "Verdict": "FIX FIRST",
            "Reviewed-SHA": "abc123def4567890",
            "Base-SHA": "abc123def4567890",
            "Findings": "FIX FIRST",
            "Verification": "scripts/issue-pipeline verify -- pytest backend/tests -q",
            "Pytest": "passed",
            "Tasks-checked": "1/1",
        },
        head_sha="abc123def4567890",
    )
    issue = state.issues["1"]
    assert issue.state == REVIEWING
    assert issue.fix_round == 1
    assert len(issue.review_history) == before_history
    assert issue.findings == "- prior finding"
    assert issue.review_malformed == 1


def test_cli_review_handoff_rejects_missing_findings(tmp_path: Path, capsys):
    from scripts.issue_pipeline.cli import main
    from scripts.issue_pipeline.gitrepo import GitRepo

    repo = tmp_path / "repo"
    repo.mkdir()
    git = GitRepo(repo)
    git.run(["init"])
    git.run(["config", "user.email", "t@example.com"])
    git.run(["config", "user.name", "t"])
    (repo / "README").write_text("x\n", encoding="utf-8")
    git.run(["add", "README"])
    git.run(["commit", "-m", "init"])
    sha = git.rev_parse(repo)

    state = BatchState()
    state.issues["1"] = IssueRecord(
        key="1",
        number=1,
        state=REVIEWING,
        worktree=str(repo),
        base_sha=sha,
    )
    store = StateStore(tmp_path / "state.json")
    store.save(state)

    handoff = tmp_path / "review.txt"
    handoff.write_text(
        "\n".join(
            [
                "REVIEW_HANDOFF",
                "Verdict: FIX FIRST",
                f"Reviewed-SHA: {sha}",
                f"Base-SHA: {sha}",
                "Findings: FIX FIRST",
                "Verification: scripts/issue-pipeline verify -- pytest backend/tests -q",
                "Pytest: passed",
                "Tasks-checked: 1/1",
            ]
        ),
        encoding="utf-8",
    )
    code = main(
        [
            "--state",
            str(store.path),
            "--repo",
            str(repo),
            "handoff",
            "--issue",
            "1",
            "--kind",
            "review",
            "--file",
            str(handoff),
        ]
    )
    assert code == 0
    payload = state = store.load()
    issue = payload.issues["1"]
    assert issue.review_malformed == 1
    assert issue.state == REVIEWING


def test_escalation_after_substantive_repeat_finding():
    state = plan("1\n", [snapshot(1)])
    state.escalation_enabled = True
    state.escalation_premium_slug = "grok-4.7-high"
    issue = state.issues["1"]
    issue.base_sha = "abc123def4567890"
    sha = issue.base_sha
    issue.state = REVIEWING
    issue.fix_round = 1
    fields = {
        "Verdict": "FIX FIRST",
        "Reviewed-SHA": sha,
        "Base-SHA": sha,
        "Findings": "- Service still omits auth on DELETE /api/resources",
        "Verification": "scripts/issue-pipeline verify -- pytest backend/tests -q",
        "Pytest": "passed",
        "Tasks-checked": "1/1",
    }
    apply_review_handoff(state, "1", fields, head_sha=sha)
    issue.last_review_findings = "- Service still omits auth on DELETE /api/resources"
    issue.state = REVIEWING
    apply_review_handoff(
        state,
        "1",
        {
            **fields,
            "Findings": "- Service still omits auth on DELETE /api/resources",
        },
        head_sha=sha,
    )
    assert issue.premium_pending is True
    assert issue.model_slug == "grok-4.7-high"


def test_record_worker_model_confirmation(tmp_path: Path):
    from scripts.issue_pipeline.scheduler import record_worker_attachment

    state = plan("1\n", [snapshot(1)])
    record_worker_attachment(
        state,
        "1",
        phase="implement",
        task_id="task-abc",
        requested_model="grok-4.7-high",
        confirmed_model="grok-4.7-high",
        model_verified="yes",
    )
    issue = state.issues["1"]
    assert issue.model_confirmed == "grok-4.7-high"
    assert issue.worker_runs[-1]["model_verified"] == "yes"

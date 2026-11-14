import json
import os
from pathlib import Path

import pytest

from scripts.issue_pipeline.decisions import CheckResult, PrView, ReviewBinding, decide
from scripts.issue_pipeline.gitrepo import discover_main_checkout
from scripts.issue_pipeline.pipeline_config import (
    load_required_checks_from_config,
    parse_required_checks_json,
    resolve_required_checks,
)
from scripts.issue_pipeline.tests.test_decisions import _binding, _pr

NINE = [
    "Backend Tests",
    "Docker Build",
    "Documentation Site",
    "Frontend Validation",
    "SDK Validation",
    "TypeScript SDK (Node 22)",
    "TypeScript SDK (Node 24)",
    "Production Auth Smoke Tests",
    "Production Compose E2E Smoke Test",
]


def _checks_for(names: list[str]) -> tuple[CheckResult, ...]:
    return tuple(CheckResult(name, "success") for name in names)


def test_repo_config_loads_from_primary_root_not_worktree_cwd(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    worktree = tmp_path / "linked"
    worktree.mkdir()
    for repo in (main, worktree):
        (repo / ".git").write_text("gitdir: nowhere")
    (main / "config").mkdir()
    (main / "config" / "issue-pipeline.json").write_text(
        json.dumps({"required_checks": ["Backend Tests"]}),
        encoding="utf-8",
    )

    class _Git:
        def run(self, args, **_kwargs):
            class _Done:
                stdout = "\n".join(
                    [
                        f"worktree {main}",
                        "branch refs/heads/main",
                        "",
                        f"worktree {worktree}",
                        f"branch refs/heads/feature/x",
                        "",
                    ]
                )

            return _Done()

    import scripts.issue_pipeline.gitrepo as gitrepo_mod

    original = gitrepo_mod.subprocess.run

    def fake_run(cmd, **_kwargs):
        if (
            len(cmd) >= 5
            and cmd[0] == "git"
            and cmd[1] == "-C"
            and Path(cmd[2]) == worktree
            and cmd[3:5] == ["worktree", "list"]
        ):
            class _Done:
                returncode = 0
                stdout = f"worktree {main}\nbranch refs/heads/main\n\nworktree {worktree}\n"
                stderr = ""

            return _Done()
        return original(cmd, **_kwargs)

    gitrepo_mod.subprocess.run = fake_run
    try:
        primary = discover_main_checkout(worktree)
        assert primary == main
        assert load_required_checks_from_config(primary) == ["Backend Tests"]
        assert load_required_checks_from_config(worktree) is None
    finally:
        gitrepo_mod.subprocess.run = original


def test_precedence_env_over_rules_and_file(monkeypatch):
    monkeypatch.setenv("PIPELINE_REQUIRED_CHECKS", "Env Check,Env Check")
    rules = [
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "Rules Check"}]},
        }
    ]
    repo = Path(__file__).resolve().parents[3]
    assert resolve_required_checks(rules_payload=rules, protection_payload=None, repo_root=repo) == [
        "Env Check"
    ]


def test_rules_before_file_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("PIPELINE_REQUIRED_CHECKS", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "issue-pipeline.json").write_text(
        json.dumps({"required_checks": NINE}),
        encoding="utf-8",
    )
    rules = [
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "Rules Check"}]},
        }
    ]
    assert resolve_required_checks(rules_payload=rules, protection_payload=None, repo_root=tmp_path) == [
        "Rules Check"
    ]


def test_file_fallback_when_github_has_no_required_checks(monkeypatch, tmp_path):
    monkeypatch.delenv("PIPELINE_REQUIRED_CHECKS", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "issue-pipeline.json").write_text(
        json.dumps({"required_checks": NINE[:3]}),
        encoding="utf-8",
    )
    rules = [{"type": "pull_request"}]
    assert resolve_required_checks(rules_payload=rules, protection_payload=None, repo_root=tmp_path) == NINE[:3]


def test_missing_config_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("PIPELINE_REQUIRED_CHECKS", raising=False)
    assert (
        resolve_required_checks(rules_payload=[{"type": "pull_request"}], protection_payload=None, repo_root=tmp_path)
        is None
    )


def test_malformed_config_fails_closed(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "issue-pipeline.json").write_text("{not json", encoding="utf-8")
    assert load_required_checks_from_config(tmp_path) is None
    assert parse_required_checks_json({"required_checks": [1, 2]}) is None
    assert parse_required_checks_json({"required_checks": []}) is None


def test_versioned_config_matches_production_list():
    repo = Path(__file__).resolve().parents[3]
    loaded = load_required_checks_from_config(repo)
    assert loaded == NINE


def test_check_failure_blocks_merge():
    checks = _checks_for(NINE)
    failing = list(checks)
    failing[0] = CheckResult("Backend Tests", "failure", "https://ci.example/fail")
    decision = decide(
        _pr(checks=tuple(failing)),
        _binding(),
        NINE,
        overlap="same-base",
        independent_review="READY",
    )
    assert decision.action == "needs-fix"
    assert decision.use_admin is False


def test_missing_required_check_blocks_merge():
    decision = decide(
        _pr(checks=_checks_for(NINE[:8])),
        _binding(),
        NINE,
        overlap="same-base",
        independent_review="READY",
    )
    assert decision.action == "wait"
    assert "missing" in decision.reason

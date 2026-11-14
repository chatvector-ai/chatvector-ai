import json
from pathlib import Path

import pytest

from scripts.issue_pipeline.gitrepo import GitRepo
from scripts.issue_pipeline.migration_guard import assert_migration_ledger_compatible
from scripts.issue_pipeline.models import MERGED, PENDING_CI, BatchState, IssueRecord, PipelineError
from scripts.issue_pipeline.publisher import finalize_issue
from scripts.issue_pipeline.reporting import build_batch_report, render_markdown_report
from scripts.issue_pipeline.scheduler import complete_merge, reconcile
from scripts.issue_pipeline.state import StateStore
from scripts.issue_pipeline.tests.test_publisher import FakeGit, FakeHub, _open_pr, _ready_store


def _git_repo_with_remotes(tmp_path: Path) -> tuple[GitRepo, dict[str, str]]:
    import os
    import subprocess

    root = tmp_path / "primary"
    root.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Pipeline Test",
            "GIT_AUTHOR_EMAIL": "pipeline@example.com",
            "GIT_COMMITTER_NAME": "Pipeline Test",
            "GIT_COMMITTER_EMAIL": "pipeline@example.com",
        }
    )

    def run(*args):
        completed = subprocess.run(
            [
                "git",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "user.name=Pipeline Test",
                "-c",
                "user.email=pipeline@example.com",
                *args,
            ],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        return completed.stdout.strip()

    run("init", "-b", "main")
    (root / "README").write_text("base\n", encoding="utf-8")
    run("add", "README")
    run("commit", "-m", "base")
    base = run("rev-parse", "HEAD")
    run("remote", "add", "upstream", str(root))
    run("remote", "add", "origin", str(root))
    run("update-ref", "refs/remotes/upstream/main", base)
    run("update-ref", "refs/remotes/origin/main", base)
    shas = {"base": base}
    for index in range(1, 4):
        (root / f"c{index}.txt").write_text(f"{index}\n", encoding="utf-8")
        run("add", f"c{index}.txt")
        run("commit", "-m", f"c{index}")
        shas[f"c{index}"] = run("rev-parse", "HEAD")
        run("update-ref", "refs/remotes/upstream/main", shas[f"c{index}"])
    return GitRepo(root), shas


def test_dirty_primary_blocks_rebase_but_reports_stale_merge(tmp_path: Path):
    git, shas = _git_repo_with_remotes(tmp_path)
    (git.root / "local-edit").write_text("dirty\n", encoding="utf-8")
    merge_sha = shas["c3"]
    sync = git.sync_primary_main(merge_sha=merge_sha)
    assert sync["status"] in {"blocked_dirty", "origin_only"}
    assert sync["primary_clean"] is False
    assert sync["merge_sha"] == merge_sha
    assert sync["merge_sha_on_primary_head"] is False
    assert sync["github_merge_success"] is True


def test_clean_primary_syncs_and_merge_is_on_head(tmp_path: Path):
    git, shas = _git_repo_with_remotes(tmp_path)
    merge_sha = shas["c2"]
    sync = git.sync_primary_main(merge_sha=merge_sha)
    assert sync["status"] == "synced"
    assert sync["merge_sha_on_primary_head"] is True
    assert sync["origin_matches_upstream"] is True


def test_empty_merge_sha_does_not_complete_observed_merge(tmp_path: Path):
    store, _issue = _ready_store(tmp_path)
    saved = store.load()
    saved.issues["12"].state = PENDING_CI
    saved.issues["12"].pr_number = 8
    store.save(saved)
    hub = FakeHub()
    from dataclasses import replace

    hub.prs[8] = replace(_open_pr(8), state="MERGED", merge_sha=None)
    result = finalize_issue(store, FakeGit(), hub, "12", lock_path=tmp_path / "merge.lock")
    assert result["action"] == "merge-incomplete"
    issue = store.load().issues["12"]
    assert issue.state != MERGED
    assert not issue.merge_sha


def test_batch_report_distinguishes_github_complete_and_primary_stale(tmp_path: Path):
    git, shas = _git_repo_with_remotes(tmp_path)
    state = BatchState()
    state.issues["652"] = IssueRecord(
        key="652",
        number=652,
        title="Page spans",
        state=MERGED,
        merge_sha=shas["c3"],
        primary_sync={
            "status": "blocked_dirty",
            "merge_sha": shas["c3"],
            "merge_sha_on_primary_head": False,
        },
    )
    report = build_batch_report(state, git=git, primary_root=git.root)
    completion = report["completion"]
    assert completion["github_merges"]["status"] == "complete"
    assert completion["primary_checkout"]["status"] == "stale"
    assert completion["status"] == "complete-github-primary-stale"
    assert report["primary_git"]["merge_reachability"][shas["c3"]]["on_canonical_main"] is True
    assert report["primary_git"]["merge_reachability"][shas["c3"]]["on_primary_head"] is False
    md = render_markdown_report(report)
    assert "complete-github-primary-stale" in md or "primary checkout stale" in md
    assert "origin/main" in md


def test_batch_report_current_when_primary_contains_merges(tmp_path: Path):
    git, shas = _git_repo_with_remotes(tmp_path)
    git.sync_primary_main(merge_sha=shas["c2"])
    state = BatchState()
    state.issues["1"] = IssueRecord(
        key="1",
        number=1,
        title="One",
        state=MERGED,
        merge_sha=shas["c2"],
    )
    report = build_batch_report(state, git=git, primary_root=git.root)
    assert report["completion"]["primary_checkout"]["status"] == "current"
    assert report["completion"]["status"] == "complete"


def test_reconcile_refuses_merged_pr_without_merge_sha():
    from scripts.issue_pipeline.dependencies import IssueSnapshot
    from scripts.issue_pipeline.tests.support import plan

    state = plan("2\n", [IssueSnapshot(2, "Two")])
    state.issues["2"].state = PENDING_CI
    state.issues["2"].pr_number = 9

    class Pr:
        state = "MERGED"
        number = 9
        merge_sha = None

    notes = reconcile(state, pr_for=lambda issue: Pr())
    assert state.issues["2"].state == PENDING_CI
    assert any("missing merge SHA" in note for note in notes)


def test_complete_merge_rejects_empty_sha():
    state = BatchState()
    state.issues["1"] = IssueRecord(key="1", state=PENDING_CI)
    with pytest.raises(Exception) as exc:
        complete_merge(state, state.issues["1"], "", "squash")
    assert "merge SHA" in str(exc.value)


def test_migration_guard_refuses_extra_ledger_rows(tmp_path: Path):
    checkout = tmp_path / "wt"
    init_dir = checkout / "backend" / "db" / "init"
    init_dir.mkdir(parents=True)
    (init_dir / "018_example.sql").write_text("-- x", encoding="utf-8")

    def reader():
        return {"018_example.sql", "019_document_chunks_page_end.sql"}

    with pytest.raises(PipelineError) as exc:
        assert_migration_ledger_compatible(checkout, reader=reader)
    assert "019_document_chunks_page_end.sql" in str(exc.value)


def test_finalize_preserves_merge_sha_when_sync_blocked(tmp_path: Path):
    store, _issue = _ready_store(tmp_path)
    saved = store.load()
    saved.issues["12"].state = PENDING_CI
    saved.issues["12"].pr_number = 8
    store.save(saved)
    hub = FakeHub()
    hub.prs[8] = _open_pr(8)

    class DirtyPrimaryGit(FakeGit):
        def __init__(self, root):
            super().__init__()
            self.root = root

        def sync_primary_main(self, *, merge_sha=None):
            return {
                "status": "blocked_dirty",
                "merge_sha": merge_sha,
                "merge_sha_on_primary_head": False,
                "github_merge_success": True,
                "primary_dirty_paths": ["Makefile"],
            }

    git = DirtyPrimaryGit(tmp_path)
    result = finalize_issue(store, git, hub, "12", lock_path=tmp_path / "merge.lock")
    assert result["action"] == "merged"
    assert len(result["merge_sha"]) >= 7
    issue = store.load().issues["12"]
    assert issue.merge_sha == result["merge_sha"]
    assert issue.primary_sync["status"] == "blocked_dirty"

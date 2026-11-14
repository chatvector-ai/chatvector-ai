import os
from pathlib import Path

import pytest

from scripts.issue_pipeline.gitrepo import GitError, GitRepo, create_issue_worktree, remove_issue_worktree
from scripts.issue_pipeline.models import IMPLEMENTING, MERGED, NEEDS_FIX, IssueRecord


def _git(*args, cwd: Path):
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Pipeline Test"
    env["GIT_AUTHOR_EMAIL"] = "pipeline@example.com"
    env["GIT_COMMITTER_NAME"] = "Pipeline Test"
    env["GIT_COMMITTER_EMAIL"] = "pipeline@example.com"
    import subprocess

    completed = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "user.name=Pipeline Test", "-c", "user.email=pipeline@example.com", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


def _repo(tmp_path: Path) -> GitRepo:
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", "-b", "main", cwd=root)
    (root / "README").write_text("base\n", encoding="utf-8")
    _git("add", "README", cwd=root)
    _git("commit", "-m", "base", cwd=root)
    sha = _git("rev-parse", "HEAD", cwd=root)
    _git("update-ref", "refs/remotes/upstream/main", sha, cwd=root)
    return GitRepo(root)


def _issue(number: int) -> IssueRecord:
    return IssueRecord(
        key=str(number),
        number=number,
        title=f"Issue {number}",
        state=IMPLEMENTING,
    )


def test_worktrees_branch_from_upstream_main_and_stay_isolated(tmp_path, monkeypatch):
    git = _repo(tmp_path)
    monkeypatch.setenv("PIPELINE_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    base = git.rev_parse(git.root, "upstream/main")
    first = _issue(1)
    second = _issue(2)
    path_one = Path(create_issue_worktree(git, first, slug="alpha", fetch=False))
    path_two = Path(create_issue_worktree(git, second, slug="beta", fetch=False))
    assert path_one != path_two
    assert git.root.resolve() not in path_one.resolve().parents
    assert git.rev_parse(path_one) == base
    assert git.rev_parse(path_two) == base
    (path_one / "only-one.txt").write_text("one\n", encoding="utf-8")
    _git("add", "only-one.txt", cwd=path_one)
    _git("commit", "-m", "one", cwd=path_one)
    assert not (path_two / "only-one.txt").exists()
    assert git.rev_parse(path_two) == base
    assert first.base_sha == base
    assert second.branch != first.branch


def test_existing_unrelated_branch_is_not_adopted(tmp_path, monkeypatch):
    git = _repo(tmp_path)
    monkeypatch.setenv("PIPELINE_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    _git("checkout", "-b", "feature/3-issue-3", cwd=git.root)
    (git.root / "other.txt").write_text("other\n", encoding="utf-8")
    _git("add", "other.txt", cwd=git.root)
    _git("commit", "-m", "other", cwd=git.root)
    _git("checkout", "main", cwd=git.root)
    issue = _issue(3)
    issue.title = "Issue 3"
    with pytest.raises(GitError, match="refusing to adopt"):
        create_issue_worktree(git, issue, slug="issue 3", fetch=False)


def test_cleanup_refuses_dirty_active_and_unmerged_worktrees(tmp_path, monkeypatch):
    git = _repo(tmp_path)
    monkeypatch.setenv("PIPELINE_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    issue = _issue(4)
    path = Path(create_issue_worktree(git, issue, slug="cleanup", fetch=False))
    issue.state = NEEDS_FIX
    with pytest.raises(Exception, match="merged"):
        remove_issue_worktree(git, issue)
    issue.state = MERGED
    issue.worker_pid = os.getpid()
    with pytest.raises(Exception, match="active"):
        remove_issue_worktree(git, issue)
    issue.worker_pid = None
    (path / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(Exception, match="uncommitted"):
        remove_issue_worktree(git, issue)
    assert path.exists()
    (path / "dirty.txt").unlink()
    remove_issue_worktree(git, issue)
    assert not path.exists()
    assert git.branch_exists(issue.branch) is False


def test_publisher_push_does_not_checkout(tmp_path):
    git = GitRepo(tmp_path)
    commands = []

    def run(args, cwd=None, check=True):
        commands.append(args)
        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""
        return Completed()

    git.run = run
    git.push(tmp_path / "wt", "origin", "feature/1-demo")
    assert commands == [["push", "origin", "HEAD:refs/heads/feature/1-demo"]]
    assert all(command[0] != "checkout" for command in commands)

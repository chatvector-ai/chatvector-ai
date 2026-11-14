"""Git operations for worktrees. Publishing never checks out a worker branch."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .locks import pid_alive
from .models import CleanupRefused, IssueRecord, PipelineError

_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


class GitError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, "git")


def discover_main_checkout(start: Path | None = None) -> Path:
    """Return the primary worktree, even when `start` is a linked worktree."""

    cwd = start or Path.cwd()
    completed = subprocess.run(
        ["git", "-C", str(cwd), "worktree", "list", "--porcelain"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GitError((completed.stderr or "git worktree list failed").strip())
    for line in completed.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line.split(" ", 1)[1])
    raise GitError("git worktree list returned no checkout")


def slugify(title: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (slug[:limit].strip("-") or "change")


def sanitize_key(key: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._+-]+", "-", key).strip("-")
    return cleaned[:80] or "work"


def worktree_root_for(repo_root: Path) -> Path:
    override = os.environ.get("PIPELINE_WORKTREE_ROOT")
    if override:
        return Path(override)
    return repo_root.parent / "chatvector-worktrees"


class GitRepo:
    def __init__(self, root: Path):
        self.root = Path(root)

    def run(self, args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        command = ["git", *args]
        completed = subprocess.run(
            command,
            cwd=cwd or self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise GitError(f"git {' '.join(args)} failed: {detail}")
        return completed

    def rev_parse(self, cwd: Path, ref: str = "HEAD") -> str:
        completed = self.run(["rev-parse", ref], cwd=cwd)
        return completed.stdout.strip()

    def status_clean(self, cwd: Path) -> bool:
        completed = self.run(["status", "--porcelain"], cwd=cwd)
        return completed.stdout.strip() == ""

    def current_branch(self, cwd: Path) -> str:
        completed = self.run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
        return completed.stdout.strip()

    def commit_exists(self, sha: str) -> bool:
        if not sha or not _SHA.fullmatch(sha):
            return False
        completed = self.run(["cat-file", "-e", f"{sha}^{{commit}}"], check=False)
        return completed.returncode == 0

    def safe_rev_parse(self, ref: str, *, cwd: Path | None = None) -> str | None:
        completed = self.run(["rev-parse", ref], cwd=cwd or self.root, check=False)
        if completed.returncode != 0:
            return None
        value = completed.stdout.strip()
        return value if _SHA.fullmatch(value) else None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        if not self.commit_exists(ancestor) or not self.commit_exists(descendant):
            return False
        completed = self.run(
            ["merge-base", "--is-ancestor", ancestor, descendant],
            check=False,
        )
        return completed.returncode == 0

    def ahead_behind(self, left: str, right: str) -> tuple[int, int]:
        """Return (commits reachable from left but not right, the converse)."""

        if not self.commit_exists(left) or not self.commit_exists(right):
            return 0, 0
        completed = self.run(
            ["rev-list", "--left-right", "--count", f"{left}...{right}"],
            check=False,
        )
        if completed.returncode != 0:
            return 0, 0
        parts = completed.stdout.strip().split()
        if len(parts) != 2:
            return 0, 0
        return int(parts[0]), int(parts[1])

    def dirty_paths(self, cwd: Path | None = None) -> list[str]:
        completed = self.run(["status", "--porcelain"], cwd=cwd or self.root, check=False)
        paths: list[str] = []
        for line in completed.stdout.splitlines():
            line = line.strip()
            if len(line) > 3:
                paths.append(line[3:].strip())
        return paths

    def branch_exists(self, name: str) -> bool:
        completed = self.run(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], check=False)
        return completed.returncode == 0

    def diff_names(self, base: str, head: str) -> set[str] | None:
        if not self.commit_exists(base) or not self.commit_exists(head):
            return None
        completed = self.run(["diff", "--name-only", f"{base}...{head}"], check=False)
        if completed.returncode != 0:
            completed = self.run(["diff", "--name-only", base, head], check=False)
        if completed.returncode != 0:
            return None
        return {line.strip() for line in completed.stdout.splitlines() if line.strip()}

    def fetch(self, remote: str = "upstream") -> None:
        self.run(["fetch", remote])

    def push(
        self,
        cwd: Path,
        remote: str,
        branch: str,
        *,
        force_with_lease_sha: str | None = None,
    ) -> None:
        """Push without changing HEAD in this or any other worktree."""

        ref = f"refs/heads/{branch}"
        if force_with_lease_sha:
            if not _SHA.fullmatch(force_with_lease_sha):
                raise GitError("force-with-lease requires a valid expected remote SHA")
            lease = f"{branch}:{force_with_lease_sha}"
            self.run(
                ["push", "--force-with-lease", lease, remote, f"HEAD:{ref}"],
                cwd=cwd,
            )
            return
        completed = self.run(
            ["push", remote, f"HEAD:{ref}"],
            cwd=cwd,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise GitError(f"git push failed: {detail}")

    def worktree_add_new(self, path: Path, branch: str, start_sha: str) -> None:
        self._assert_outside(path)
        self.run(["worktree", "add", "-b", branch, str(path), start_sha])

    def worktree_add_existing(self, path: Path, branch: str) -> None:
        self._assert_outside(path)
        self.run(["worktree", "add", str(path), branch])

    def remove_worktree(self, path: Path) -> None:
        self.run(["worktree", "remove", str(path)])

    def delete_local_branch(self, name: str) -> None:
        completed = self.run(["branch", "-d", name], check=False)
        if completed.returncode == 0:
            return
        self.run(["branch", "-D", name])

    def sync_primary_main(self, *, merge_sha: str | None = None) -> dict:
        """Post-merge sync: rebase a clean primary checkout or update origin without touching it.

        Never resets, stashes, or discards user changes on the primary checkout.
        """

        from .sync_state import PrimarySyncResult, enrich_sync_result

        branch = self.current_branch(self.root)
        clean = self.status_clean(self.root)
        dirty_paths = [] if clean else self.dirty_paths(self.root)
        result = PrimarySyncResult(
            primary_branch=branch,
            primary_clean=clean,
            primary_dirty_paths=dirty_paths,
            primary_head=self.rev_parse(self.root),
        )
        try:
            self.fetch("upstream")
        except GitError as exc:
            result.status = "fetch_failed"
            result.message = str(exc)
            return enrich_sync_result(result, self, merge_sha or "")

        result.upstream_main = self.safe_rev_parse("upstream/main") or ""
        result.origin_main = self.safe_rev_parse("origin/main")

        if branch == "main" and clean:
            result.primary_rebase_attempted = True
            try:
                self.run(["rebase", "upstream/main"])
                self.run(["push", "--force-with-lease", "origin", "HEAD"])
                result.primary_rebase_succeeded = True
                result.origin_push_attempted = True
                result.origin_push_succeeded = True
                result.status = "synced"
            except GitError as exc:
                result.status = "rebase_failed"
                result.message = str(exc)
        else:
            if branch != "main":
                result.status = "blocked_not_main"
                result.message = "primary checkout is not on main"
            else:
                result.status = "blocked_dirty"
                result.message = "primary checkout is dirty"
            result.origin_push_attempted = True
            pushed = self.run(
                [
                    "push",
                    "--force-with-lease",
                    "origin",
                    "refs/remotes/upstream/main:refs/heads/main",
                ],
                check=False,
            )
            if pushed.returncode == 0:
                result.origin_push_succeeded = True
                if result.status.startswith("blocked"):
                    result.status = "origin_only"
            elif not result.message:
                detail = (pushed.stderr or pushed.stdout or "").strip()
                result.message = detail or "origin main could not be updated"

        result.primary_head = self.rev_parse(self.root)
        result.origin_main = self.safe_rev_parse("origin/main")
        result.origin_matches_upstream = bool(
            result.origin_main and result.upstream_main and result.origin_main == result.upstream_main
        )
        return enrich_sync_result(result, self, merge_sha or "")

    def _assert_outside(self, path: Path) -> None:
        repo = self.root.resolve()
        target = path.resolve()
        if target == repo or repo in target.parents:
            raise GitError(f"worktree {target} must stay outside the main checkout")


def branch_name_for(issue: IssueRecord, slug: str) -> str:
    if issue.mode == "audit-fix":
        return f"fix/audit-{slugify(slug)}"
    return f"feature/{issue.number}-{slugify(slug)}"


def create_issue_worktree(
    git: GitRepo,
    issue: IssueRecord,
    *,
    slug: str,
    fetch: bool = True,
    root: Path | None = None,
) -> str:
    """Create or reuse a worktree branched from upstream/main, never from another issue."""

    destination_root = root or worktree_root_for(git.root)
    path = Path(issue.worktree) if issue.worktree else destination_root / f"issue-{sanitize_key(issue.key)}"
    if path.exists():
        _validate_existing(git, issue, path)
        issue.worktree = str(path)
        return issue.worktree
    if fetch:
        git.fetch("upstream")
    base = git.rev_parse(git.root, "upstream/main")
    branch = issue.branch or branch_name_for(issue, slug)
    if git.branch_exists(branch):
        tip = git.rev_parse(git.root, branch)
        allowed = {
            value
            for value in (issue.head_sha, issue.reviewed_sha, issue.base_sha, base)
            if value
        }
        if tip not in allowed:
            raise GitError(
                f"refusing to adopt {branch} at {tip}; it does not match pipeline state"
            )
        if issue.head_sha and issue.base_sha and issue.base_sha != base and tip == base:
            raise GitError("refusing to recreate a reviewed branch from a newer upstream/main")
        git.worktree_add_existing(path, branch)
    else:
        if issue.head_sha and issue.base_sha and issue.base_sha != base:
            raise GitError("refusing to recreate a missing branch from a newer upstream/main")
        git.worktree_add_new(path, branch, base)
        if not issue.base_sha:
            issue.base_sha = base
    issue.branch = branch
    if not issue.base_sha:
        issue.base_sha = base
    issue.worktree = str(path)
    return issue.worktree


def remove_issue_worktree(git: GitRepo, issue: IssueRecord) -> None:
    if issue.state != "merged":
        raise CleanupRefused("cleanup only runs after the pull request is merged")
    if pid_alive(issue.worker_pid):
        raise CleanupRefused("cleanup refused while a worker is active")
    if issue.correction_kind:
        raise CleanupRefused("cleanup refused while a correction is pending")
    if not issue.worktree:
        return
    path = Path(issue.worktree)
    if path.exists() and not git.status_clean(path):
        raise CleanupRefused("worktree has uncommitted changes")
    if path.exists():
        git.remove_worktree(path)
    if issue.branch and git.branch_exists(issue.branch):
        git.delete_local_branch(issue.branch)
    issue.worktree = None


def _validate_existing(git: GitRepo, issue: IssueRecord, path: Path) -> None:
    branch = git.current_branch(path)
    if issue.branch and branch != issue.branch:
        raise GitError(f"worktree {path} is on {branch}, expected {issue.branch}")
    if not issue.branch:
        issue.branch = branch

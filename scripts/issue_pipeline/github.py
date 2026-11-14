"""GitHub CLI helpers. Tests use fakes; this module is the real boundary."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

from pathlib import Path

from .decisions import CheckResult, PrView
from .dependencies import IssueSnapshot
from .models import PipelineError

_SLUG = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/.]+)")
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


class GitHubError(PipelineError):
    def __init__(self, message: str, kind: str = "unknown"):
        super().__init__(message, "github")
        self.kind = kind


@dataclass(frozen=True)
class RepoRef:
    upstream: str
    fork: str
    fork_owner: str


@dataclass(frozen=True)
class MergeAttempt:
    completed: bool
    merge_sha: str | None
    stdout: str
    stderr: str


def parse_github_slug(url: str) -> tuple[str, str]:
    match = _SLUG.search(url)
    if not match:
        raise GitHubError(f"cannot parse GitHub remote: {url}")
    return match.group("owner"), match.group("name")


def resolve_from_urls(origin: str, upstream: str | None) -> RepoRef:
    owner, name = parse_github_slug(origin)
    if upstream:
        up_owner, up_name = parse_github_slug(upstream)
        upstream_slug = f"{up_owner}/{up_name}"
    else:
        upstream_slug = f"{owner}/{name}"
    return RepoRef(upstream_slug, f"{owner}/{name}", owner)


def build_merge_command(
    repo: str,
    number: int,
    *,
    admin: bool,
    sha: str,
    subject: str,
    body: str,
) -> list[str]:
    if not _SHA.fullmatch(sha or ""):
        raise GitHubError("refusing to merge without the reviewed head SHA")
    command = [
        "gh",
        "pr",
        "merge",
        str(number),
        "--repo",
        repo,
        "--squash",
        "--match-head-commit",
        sha,
        "--subject",
        subject,
        "--body",
        body,
    ]
    if admin:
        command.append("--admin")
    return command


def classify_merge_failure(output: str) -> str:
    """Return review_required only when the text does not also cite checks or a queue."""

    text = output.lower()
    check_markers = (
        "required status check",
        "failing checks",
        "checks have not passed",
        "status checks",
        "check is failing",
    )
    queue_markers = ("merge queue", "auto-merge")
    review_markers = (
        "review required",
        "approving review",
        "code owner review",
        "requires review",
        "at least 1 approving review",
        "waiting for review",
    )
    if any(marker in text for marker in check_markers):
        return "checks"
    if any(marker in text for marker in queue_markers):
        return "queue"
    if any(marker in text for marker in review_markers):
        return "review_required"
    return "unknown"


def parse_rules_required_checks(payload) -> list[str] | None:
    rules = payload
    if isinstance(payload, dict):
        if payload.get("type"):
            rules = [payload]
        else:
            rules = payload.get("rules") or []
    if not isinstance(rules, list):
        return None
    saw = False
    names: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        saw = True
        params = rule.get("parameters") or {}
        for item in params.get("required_status_checks") or []:
            if isinstance(item, str) and item:
                names.append(item)
            elif isinstance(item, dict):
                context = item.get("context") or item.get("name")
                if context:
                    names.append(context)
    if not saw:
        return None
    return _unique(names)


def parse_protection_checks(payload: dict) -> list[str] | None:
    if not isinstance(payload, dict):
        return None
    names: list[str] = []
    for context in payload.get("contexts") or []:
        if context:
            names.append(context)
    for check in payload.get("checks") or []:
        if isinstance(check, dict) and check.get("context"):
            names.append(check["context"])
    if "contexts" not in payload and "checks" not in payload:
        return None
    return _unique(names)


def parse_check_runs(payload: dict, sha: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    for run in payload.get("check_runs") or []:
        name = run.get("name") or ""
        if not name:
            continue
        head = run.get("head_sha") or sha
        if head != sha:
            conclusion = "stale"
        else:
            conclusion = map_conclusion(run.get("status"), run.get("conclusion"))
        url = run.get("html_url") or run.get("details_url") or ""
        results.append(CheckResult(name, conclusion, url))
    return results


def parse_statuses(payload: dict) -> list[CheckResult]:
    results: list[CheckResult] = []
    seen: set[str] = set()
    for status in payload.get("statuses") or []:
        context = status.get("context")
        if not context or context in seen:
            continue
        seen.add(context)
        state = (status.get("state") or "").lower()
        mapped = {
            "success": "success",
            "failure": "failure",
            "error": "failure",
            "pending": "pending",
        }.get(state, "unknown")
        results.append(CheckResult(context, mapped, status.get("target_url") or ""))
    return results


def map_conclusion(status: str | None, conclusion: str | None) -> str:
    if (status or "").upper() != "COMPLETED":
        return "pending"
    value = (conclusion or "").lower()
    if value == "success":
        return "success"
    if value in {"failure", "timed_out", "startup_failure", "action_required"}:
        return "failure"
    if value in {"cancelled", "skipped", "stale", "neutral"}:
        return value
    return "unknown"


def render_pr_body(issue) -> str:
    lines: list[str] = []
    if issue.mode == "issue" and issue.number:
        lines.extend([f"Closes #{issue.number}", ""])
    else:
        lines.append(f"Audit-fix `{issue.work_id}`")
        if issue.audit_report:
            lines.append(f"Report: `{issue.audit_report}`")
        lines.append("")
    lines.extend(
        [
            "## Summary",
            issue.summary or issue.title or "Pipeline submission",
            "",
            "## Review findings addressed",
            f"Reviewed-SHA: `{issue.reviewed_sha}`",
            issue.findings or "READY review reported no findings.",
            "",
            "## Testing",
            issue.verification or "See the independent review.",
            "",
            f"Base-SHA: `{issue.base_sha}`",
        ]
    )
    return "\n".join(lines) + "\n"


def render_merge_message(issue) -> tuple[str, str]:
    scope = issue.areas[0] if len(issue.areas) == 1 else "repo"
    kind = "fix" if issue.mode == "audit-fix" else "feat"
    title = (issue.title or issue.work_id or "update").strip().rstrip(".")
    subject = f"{kind}({scope}): {title}"[:120]
    lines = [issue.summary or title]
    if issue.mode == "issue" and issue.number:
        lines.append(f"Closes #{issue.number}")
    else:
        lines.append(f"Audit-fix {issue.work_id}")
        if issue.audit_report:
            lines.append(f"Report: {issue.audit_report}")
    return subject, "\n".join(lines) + "\n"


def areas_from_paths(paths: set[str]) -> list[str]:
    scopes: list[str] = []
    for path in sorted(paths):
        if path.startswith("backend/"):
            scope = "backend"
        elif path.startswith("frontend-demo/") or path.startswith("frontend/"):
            scope = "frontend"
        elif path.startswith("sdk/"):
            scope = "sdk"
        elif path.startswith("documentation/") or path.startswith("docs/"):
            scope = "docs"
        elif path.startswith(".github/"):
            scope = "ci"
        else:
            scope = "repo"
        if scope not in scopes:
            scopes.append(scope)
    if len(scopes) == 1:
        return scopes
    return ["repo"]


def _unique(names: list[str]) -> list[str]:
    seen: list[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


class GitHubClient:
    """Thin `gh` wrapper. Refuses to change branch protection."""

    def __init__(self, repos: RepoRef, *, repo_root: Path | None = None):
        self.repos = repos
        self.repo_root = Path(repo_root) if repo_root else None
        self.last_error = ""

    def resolve_repos(self) -> RepoRef:
        return self.repos

    def issue_snapshot(self, number: int) -> IssueSnapshot:
        payload = self._gh_json(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                self.repos.upstream,
                "--json",
                "number,title,body,state",
            ]
        )
        return IssueSnapshot(
            number=int(payload["number"]),
            title=payload.get("title") or "",
            body=payload.get("body") or "",
            closed=str(payload.get("state") or "").upper() == "CLOSED",
            blocked_by=self._blocked_by(number),
        )

    def _blocked_by(self, number: int) -> list[int]:
        owner, name = self.repos.upstream.split("/", 1)
        query = (
            "query($owner:String!,$name:String!,$number:Int!){"
            "repository(owner:$owner,name:$name){issue(number:$number){"
            "blockedBy(first:20){nodes{number}}}}}"
        )
        completed = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={name}",
                "-F",
                f"number={number}",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self.last_error = (completed.stderr or completed.stdout or "").strip()
            return []
        try:
            nodes = (
                json.loads(completed.stdout)["data"]["repository"]["issue"]["blockedBy"]["nodes"]
            )
        except (KeyError, TypeError, json.JSONDecodeError):
            return []
        return [int(node["number"]) for node in nodes if node.get("number")]

    def find_open_pr(self, fork_owner: str, branch: str) -> PrView | None:
        payload = self._gh_json(
            [
                "pr",
                "list",
                "--repo",
                self.repos.upstream,
                "--head",
                f"{fork_owner}:{branch}",
                "--state",
                "open",
                "--json",
                "number",
            ]
        )
        if not payload:
            return None
        if len(payload) > 1:
            raise GitHubError(f"multiple open pull requests for {branch}")
        return self.get_pr(int(payload[0]["number"]))

    def get_pr(self, number: int) -> PrView:
        payload = self._gh_json(
            [
                "pr",
                "view",
                str(number),
                "--repo",
                self.repos.upstream,
                "--json",
                "number,state,isDraft,headRefOid,baseRefOid,baseRefName,mergeable,mergeStateStatus,reviewDecision,url,mergeCommit",
            ]
        )
        head = payload.get("headRefOid") or ""
        checks = self.checks_for(head) or []
        merge_commit = payload.get("mergeCommit") or {}
        merge_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
        return PrView(
            number=int(payload["number"]),
            state=(payload.get("state") or "").upper(),
            draft=bool(payload.get("isDraft")),
            head_sha=head,
            base_sha=payload.get("baseRefOid") or "",
            base_ref=payload.get("baseRefName") or "",
            mergeable=(payload.get("mergeable") or "UNKNOWN").upper(),
            merge_state=(payload.get("mergeStateStatus") or "UNKNOWN").upper(),
            review_decision=(payload.get("reviewDecision") or "") or "",
            checks=tuple(checks),
            url=payload.get("url") or "",
            merge_sha=merge_sha,
        )

    def checks_for(self, sha: str) -> list[CheckResult] | None:
        if not sha:
            return None
        runs = self._api_json(f"repos/{self.repos.upstream}/commits/{sha}/check-runs")
        statuses = self._api_json(f"repos/{self.repos.upstream}/commits/{sha}/status")
        if runs is None and statuses is None:
            return None
        checks: list[CheckResult] = []
        if isinstance(runs, dict):
            checks.extend(parse_check_runs(runs, sha))
        if isinstance(statuses, dict):
            checks.extend(parse_statuses(statuses))
        return checks

    def required_checks(self) -> list[str] | None:
        from .pipeline_config import resolve_required_checks

        rules = self._api_json(f"repos/{self.repos.upstream}/rules/branches/main")
        protection = self._api_json(
            f"repos/{self.repos.upstream}/branches/main/protection/required_status_checks"
        )
        return resolve_required_checks(
            rules_payload=rules,
            protection_payload=protection if isinstance(protection, dict) else None,
            repo_root=self.repo_root,
        )

    def create_pr(self, *, branch: str, title: str, body: str) -> PrView:
        completed = self._gh(
            [
                "pr",
                "create",
                "--repo",
                self.repos.upstream,
                "--base",
                "main",
                "--head",
                f"{self.repos.fork_owner}:{branch}",
                "--title",
                title,
                "--body",
                body,
            ]
        )
        match = re.search(r"/pull/(\d+)", completed.stdout)
        if not match:
            raise GitHubError(f"could not parse created pull request URL: {completed.stdout.strip()}")
        return self.get_pr(int(match.group(1)))

    def update_pr(self, number: int, *, title: str, body: str) -> PrView:
        self._gh(
            [
                "pr",
                "edit",
                str(number),
                "--repo",
                self.repos.upstream,
                "--title",
                title,
                "--body",
                body,
            ]
        )
        return self.get_pr(number)

    def merge(
        self,
        number: int,
        *,
        admin: bool,
        sha: str,
        subject: str,
        body: str,
    ) -> MergeAttempt:
        command = build_merge_command(
            self.repos.upstream,
            number,
            admin=admin,
            sha=sha,
            subject=subject,
            body=body,
        )
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        pr = self.get_pr(number)
        output = f"{completed.stdout}\n{completed.stderr}"
        if pr.state == "MERGED":
            return MergeAttempt(True, pr.merge_sha, completed.stdout, completed.stderr)
        if completed.returncode != 0:
            raise GitHubError(output.strip() or "merge failed", classify_merge_failure(output))
        return MergeAttempt(False, None, completed.stdout, completed.stderr)

    def _gh_json(self, args: list[str]):
        completed = self._gh(args)
        return json.loads(completed.stdout or "null")

    def _gh(self, args: list[str]) -> subprocess.CompletedProcess:
        completed = subprocess.run(
            ["gh", *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise GitHubError((completed.stderr or completed.stdout or "gh failed").strip())
        return completed

    def _api_json(self, path: str):
        completed = subprocess.run(
            ["gh", "api", path],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self.last_error = (completed.stderr or completed.stdout or "").strip()
            return None
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            self.last_error = "GitHub returned non-JSON rule data"
            return None

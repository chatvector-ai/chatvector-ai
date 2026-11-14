"""Command line for the issue pipeline.

The orchestrator delegates GitHub publication to these subcommands. Implement
and review stay in fresh agent sessions; this process does not call a model.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .dependencies import IssueSnapshot, build_batch, collect_snapshots
from .gitrepo import (
    GitRepo,
    create_issue_worktree,
    discover_main_checkout,
    remove_issue_worktree,
    sanitize_key,
    worktree_root_for,
)
from .github import GitHubClient, RepoRef, resolve_from_urls
from .locks import command_needs_lock, run_locked, run_verified
from .migration_guard import assert_migration_ledger_compatible
from .models import BatchState, IssueRecord, PipelineError
from .poll_ci import poll_ci
from .publisher import finalize_issue, submit, tick
from .reporting import build_batch_report, render_markdown_report
from .runtime_env import prepend_tool_path
from .queue import parse_queue
from .handoffs import parse_handoff
from .scheduler import (
    apply_implement_handoff,
    apply_review_handoff,
    attach_worker,
    authorize_premium_rescue,
    authorize_rebase,
    block_issue,
    claim,
    dry_run,
    next_actions,
    plan_audit,
    reconcile,
    record_integration,
    record_worker_attachment,
    retry_ci,
)
from .state import StateStore


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        prepend_tool_path(_primary(args))
    except PipelineError:
        pass
    try:
        payload = args.func(args)
    except PipelineError as exc:
        return _emit({"ok": False, "error": exc.code, "message": str(exc)}, _exit_code(exc))
    if payload is None:
        return 0
    return _emit(payload, 0 if payload.get("ok", True) else 1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="issue-pipeline")
    parser.add_argument("--state", help="state JSON path")
    parser.add_argument("--repo", help="main checkout path")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("issues", nargs="*")
    plan.add_argument("--queue-file")
    plan.add_argument("--queue")
    plan.add_argument("--snapshot")
    plan.add_argument("--fetch", action="store_true")
    plan.add_argument("--closed", default="")
    plan.add_argument("--concurrency", type=int)
    plan.set_defaults(func=cmd_plan)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--queue-file")
    prepare.add_argument("--queue")
    prepare.add_argument("--snapshot")
    prepare.add_argument("--fetch", action="store_true")
    prepare.add_argument("--replace", action="store_true")
    prepare.add_argument("--closed", default="")
    prepare.add_argument("--mode", choices=["issue", "audit-fix"], default="issue")
    prepare.add_argument("--work")
    prepare.add_argument("--audit-report")
    prepare.add_argument("--title", default="")
    prepare.set_defaults(func=cmd_prepare)

    nxt = sub.add_parser("next")
    nxt.set_defaults(func=cmd_next)

    claim_cmd = sub.add_parser("claim")
    claim_cmd.add_argument("--issue", required=True)
    claim_cmd.add_argument("--action", required=True, choices=["implement", "review"])
    claim_cmd.add_argument("--worker-id", required=True)
    claim_cmd.add_argument("--orchestrator")
    claim_cmd.add_argument("--pid", type=int)
    claim_cmd.set_defaults(func=cmd_claim)

    attach = sub.add_parser("attach")
    attach.add_argument("--issue", required=True)
    attach.add_argument("--expect", required=True)
    attach.add_argument("--worker-id", required=True)
    attach.add_argument("--pid", type=int)
    attach.add_argument("--phase", choices=["implement", "review"])
    attach.add_argument("--requested-model")
    attach.add_argument("--confirmed-model")
    attach.add_argument("--model-verified", choices=["yes", "no", "unknown"])
    attach.set_defaults(func=cmd_attach)

    record = sub.add_parser("record-worker")
    record.add_argument("--issue", required=True)
    record.add_argument("--phase", required=True, choices=["implement", "review"])
    record.add_argument("--task-id", required=True)
    record.add_argument("--requested-model")
    record.add_argument("--confirmed-model")
    record.add_argument("--model-verified", choices=["yes", "no", "unknown"], default="unknown")
    record.set_defaults(func=cmd_record_worker)

    tree = sub.add_parser("worktree-add")
    tree.add_argument("--issue", required=True)
    tree.add_argument("--worker-id", required=True)
    tree.add_argument("--slug")
    tree.set_defaults(func=cmd_worktree)

    handoff = sub.add_parser("handoff")
    handoff.add_argument("--issue", required=True)
    handoff.add_argument("--kind", required=True, choices=["implement", "review"])
    handoff.add_argument("--file", required=True)
    handoff.set_defaults(func=cmd_handoff)

    submit_cmd = sub.add_parser("submit")
    submit_cmd.add_argument("--issue", required=True)
    submit_cmd.add_argument("--init", action="store_true")
    submit_cmd.add_argument("--branch")
    submit_cmd.add_argument("--reviewed-sha")
    submit_cmd.add_argument("--base-sha")
    submit_cmd.add_argument("--worktree")
    submit_cmd.add_argument("--title")
    submit_cmd.add_argument("--findings")
    submit_cmd.add_argument("--verification")
    submit_cmd.add_argument("--audit-report")
    submit_cmd.add_argument("--work")
    submit_cmd.set_defaults(func=cmd_submit)

    tick_cmd = sub.add_parser("tick")
    tick_cmd.add_argument("--issue")
    tick_cmd.set_defaults(func=cmd_tick)

    poll = sub.add_parser(
        "poll-ci",
        help="poll pending-ci pull requests until merge, timeout, or agent follow-up",
    )
    poll.add_argument("--issue")
    poll.add_argument(
        "--interval",
        type=float,
        help="seconds between ticks (default PIPELINE_CI_POLL_INTERVAL or 15)",
    )
    poll.add_argument(
        "--max-wait",
        type=float,
        help="max seconds to poll (default PIPELINE_CI_POLL_MAX_WAIT or 1800)",
    )
    poll.set_defaults(func=cmd_poll_ci)

    integration = sub.add_parser("record-integration")
    integration.add_argument("--issue", required=True)
    integration.add_argument("--base", required=True)
    integration.add_argument("--result", required=True, choices=["pass", "fail"])
    integration.set_defaults(func=cmd_integration)

    rebase = sub.add_parser(
        "authorize-rebase",
        help="allow one guarded force-with-lease on the next submit",
    )
    rebase.add_argument("--issue", required=True)
    rebase.add_argument("--expected-remote-sha", required=True)
    rebase.set_defaults(func=cmd_authorize_rebase)

    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("--issue", required=True)
    cleanup.set_defaults(func=cmd_cleanup)

    resume = sub.add_parser("resume")
    resume.add_argument("--abandon", action="append", default=[])
    resume.add_argument("--orchestrator")
    resume.add_argument("--takeover", action="store_true")
    resume.set_defaults(func=cmd_resume)

    rescue = sub.add_parser(
        "rescue",
        help="authorize one premium rescue after fix-limit (operator action)",
    )
    rescue.add_argument("--issue", required=True)
    rescue.add_argument("--note", default="", help="optional operator note for the event log")
    rescue.set_defaults(func=cmd_rescue)

    block = sub.add_parser("block")
    block.add_argument("--issue", required=True)
    block.add_argument("--reason", required=True)
    block.set_defaults(func=cmd_block)

    retry = sub.add_parser("retry-ci")
    retry.add_argument("--issue", required=True)
    retry.set_defaults(func=cmd_retry)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    report = sub.add_parser("report")
    report.add_argument("--markdown", help="write Markdown report to this path")
    report.add_argument("--json", dest="json_path", help="write JSON report to this path")
    report.add_argument("--handoffs", help="directory with saved handoff text files")
    report.set_defaults(func=cmd_report)

    lock = sub.add_parser("lock")
    lock.add_argument("action", choices=["exec"])
    lock.add_argument("command", nargs=argparse.REMAINDER)
    lock.set_defaults(func=cmd_lock)

    verify = sub.add_parser("verify")
    verify.add_argument("command", nargs=argparse.REMAINDER)
    verify.set_defaults(func=cmd_verify)
    return parser


def cmd_prepare(args) -> dict:
    store = _store(args)
    if args.mode == "audit-fix":
        if not args.work or not args.audit_report:
            raise PipelineError("audit-fix requires --work and --audit-report", "graph")
        state = plan_audit(args.work, args.audit_report, args.title or args.work)
    else:
        if args.queue_file:
            text = Path(args.queue_file).read_text(encoding="utf-8")
        elif args.queue:
            text = args.queue
        else:
            raise PipelineError("prepare requires --queue-file or --queue", "graph")
        parsed = parse_queue(text)
        if args.fetch:
            hub = _github(args)
            snapshots = collect_snapshots(parsed, hub.issue_snapshot)
        elif args.snapshot:
            snapshots = _load_snapshots(Path(args.snapshot))
        else:
            raise PipelineError(
                "prepare requires --snapshot or --fetch",
                "graph",
            )
        closed = {int(item) for item in args.closed.split(",") if item.strip()}
        state = build_batch(parsed, snapshots, closed_numbers=closed, repo_root=_primary(args))
    if store.exists() and not args.replace:
        raise PipelineError(
            "pipeline state already exists; resume it or pass --replace",
            "state",
        )
    store.save(state)
    return {"ok": True, **_summary(state)}


def cmd_next(args) -> dict:
    state = _store(args).load()
    payload = next_actions(state)
    payload["ok"] = True
    payload["review_model"] = state.review_model
    payload["worker_mix"] = state.worker_mix
    payload["alternate_slug"] = state.alternate_slug
    return payload


def cmd_plan(args) -> dict:
    if args.queue_file:
        text = Path(args.queue_file).read_text(encoding="utf-8")
    elif args.queue:
        text = args.queue
    elif args.issues:
        lines = []
        if args.concurrency:
            lines.append(f"Concurrency: {args.concurrency}")
        lines.extend(str(number) for number in args.issues)
        text = "\n".join(lines) + "\n"
    else:
        raise PipelineError("plan requires issue numbers or a queue", "graph")
    parsed = parse_queue(text)
    if args.snapshot:
        snapshots = _load_snapshots(Path(args.snapshot))
    else:
        snapshots = collect_snapshots(parsed, _github(args).issue_snapshot)
    closed = {int(item) for item in args.closed.split(",") if item.strip()}
    state = build_batch(parsed, snapshots, closed_numbers=closed, repo_root=_primary(args))
    report = dry_run(state)
    root = _primary(args)
    worktrees = worktree_root_for(root)
    for item in report["issues"]:
        item["worktree"] = str(worktrees / f"issue-{sanitize_key(item['issue'])}")
    report["worktree_root"] = str(worktrees)
    report["full_suite_lock"] = str(_suite_lock_path(root))
    report["ok"] = True
    report["dry_run"] = True
    return report


def cmd_claim(args) -> dict:
    store = _store(args)
    with store.transaction() as state:
        issue = claim(
            state,
            args.issue,
            args.action,
            args.pid,
            worker_id=args.worker_id,
            orchestrator_id=args.orchestrator,
        )
        return {
            "ok": True,
            "issue": issue.key,
            "state": issue.state,
            "claimed": issue.claimed,
            "worker_id": issue.worker_id,
        }


def cmd_attach(args) -> dict:
    store = _store(args)
    with store.transaction() as state:
        issue = attach_worker(
            state,
            args.issue,
            expect=args.expect,
            worker_id=args.worker_id,
            pid=args.pid,
        )
        if args.phase:
            record_worker_attachment(
                state,
                issue.key,
                phase=args.phase,
                task_id=args.worker_id,
                requested_model=args.requested_model,
                confirmed_model=args.confirmed_model,
                model_verified=args.model_verified or "unknown",
            )
        return {"ok": True, "issue": issue.key, "worker_id": issue.worker_id}


def cmd_record_worker(args) -> dict:
    store = _store(args)
    with store.transaction() as state:
        issue = record_worker_attachment(
            state,
            args.issue,
            phase=args.phase,
            task_id=args.task_id,
            requested_model=args.requested_model,
            confirmed_model=args.confirmed_model,
            model_verified=args.model_verified,
        )
        return {
            "ok": True,
            "issue": issue.key,
            "model_confirmed": issue.model_confirmed,
            "worker_runs": issue.worker_runs[-1:],
        }


def cmd_worktree(args) -> dict:
    store = _store(args)
    git = _git(args)
    with store.transaction() as state:
        issue = state.issues[str(args.issue)]
        if issue.state not in {"implementing", "reviewing", "needs-fix"}:
            raise PipelineError(
                f"{issue.key} is {issue.state}; claim it before creating a worktree",
                "transition",
            )
        if issue.worker_id and args.worker_id != issue.worker_id:
            raise PipelineError(
                f"{issue.key} is claimed by {issue.worker_id}",
                "transition",
            )
        path = create_issue_worktree(
            git,
            issue,
            slug=args.slug or issue.title or issue.key,
        )
        state.event(issue.key, "worktree", path)
        return {
            "ok": True,
            "issue": issue.key,
            "worktree": path,
            "branch": issue.branch,
            "base_sha": issue.base_sha,
        }


def cmd_handoff(args) -> dict:
    text = Path(args.file).read_text(encoding="utf-8")
    store = _store(args)
    git = _git(args)
    header = "WORKER_HANDOFF" if args.kind == "implement" else "REVIEW_HANDOFF"
    fields = parse_handoff(text, header)
    with store.transaction() as state:
        issue = state.issues[str(args.issue)]
        if not issue.worktree:
            raise PipelineError(f"{issue.key} has no worktree", "git")
        worktree = Path(issue.worktree)
        head = git.rev_parse(worktree)
        if args.kind == "implement":
            if issue.base_sha and not git.commit_exists(issue.base_sha):
                raise PipelineError(f"base SHA {issue.base_sha} is not in this repo", "git")
            apply_implement_handoff(
                state,
                issue.key,
                fields,
                head_sha=head,
                clean=git.status_clean(worktree),
            )
        else:
            apply_review_handoff(state, issue.key, fields, head_sha=head)
        current = state.issues[issue.key]
        return {"ok": True, "issue": current.key, "state": current.state, "sha": current.head_sha}


def cmd_submit(args) -> dict:
    store = _store(args, create=args.init)
    if args.init:
        with store.transaction() as state:
            _bootstrap(state, args)
    return submit(store, _git(args), _github(args), args.issue)


def cmd_tick(args) -> dict:
    root = _root(args)
    primary = _primary(args)
    return tick(
        _store(args),
        _git(args),
        _github(args),
        lock_path=_merge_lock_path(root),
        suite_lock_path=_suite_lock_path(primary),
        only=args.issue,
    )


def cmd_poll_ci(args) -> dict:
    root = _root(args)
    primary = _primary(args)
    return poll_ci(
        _store(args),
        _git(args),
        _github(args),
        lock_path=_merge_lock_path(root),
        suite_lock_path=_suite_lock_path(primary),
        only=args.issue,
        interval=args.interval,
        max_wait=args.max_wait,
    )


def cmd_authorize_rebase(args) -> dict:
    store = _store(args)
    with store.transaction() as state:
        issue = authorize_rebase(state, args.issue, expected_remote_sha=args.expected_remote_sha)
        return {
            "ok": True,
            "issue": issue.key,
            "rebase_authorized": issue.rebase_authorized,
            "pushed_sha": issue.pushed_sha,
        }


def cmd_integration(args) -> dict:
    store = _store(args)
    git = _git(args)
    with store.transaction() as state:
        issue = state.issues[str(args.issue)]
        if not issue.worktree:
            raise PipelineError(f"{issue.key} has no worktree", "git")
        worktree = Path(issue.worktree)
        record_integration(
            state,
            issue.key,
            args.base,
            args.result,
            head_sha=git.rev_parse(worktree),
            clean=git.status_clean(worktree),
        )
        current = state.issues[issue.key]
        return {"ok": True, "issue": current.key, "state": current.state, "reason": current.reason_code}


def cmd_cleanup(args) -> dict:
    store = _store(args)
    git = _git(args)
    with store.transaction() as state:
        issue = state.issues[str(args.issue)]
        remove_issue_worktree(git, issue)
        state.event(issue.key, "cleanup", "")
        return {"ok": True, "issue": issue.key, "worktree": issue.worktree}


def cmd_rescue(args) -> dict:
    store = _store(args)
    with store.transaction() as state:
        issue = authorize_premium_rescue(state, args.issue, note=args.note or "")
        return {
            "ok": True,
            "issue": issue.key,
            "state": issue.state,
            "reason_code": issue.reason_code,
            "premium_pending": issue.premium_pending,
            "model_slug": issue.model_slug,
            "escalation_batch_count": state.escalation_batch_count,
        }


def cmd_resume(args) -> dict:
    store = _store(args)
    hub = _github(args)

    def pr_for(issue: IssueRecord):
        if not issue.pr_number:
            return None
        try:
            return hub.get_pr(issue.pr_number)
        except Exception:
            return None

    with store.transaction() as state:
        notes = reconcile(
            state,
            pr_for=pr_for,
            abandon=args.abandon,
            orchestrator_id=args.orchestrator,
            takeover=args.takeover,
        )
        return {"ok": True, "notes": notes, **_summary(state)}


def cmd_block(args) -> dict:
    store = _store(args)
    with store.transaction() as state:
        issue = block_issue(state, args.issue, args.reason)
        return {"ok": True, "issue": issue.key, "state": issue.state}


def cmd_retry(args) -> dict:
    store = _store(args)
    with store.transaction() as state:
        issue = retry_ci(state, args.issue)
        return {"ok": True, "issue": issue.key, "state": issue.state}


def cmd_status(args) -> dict:
    state = _store(args).load()
    return {"ok": True, **_summary(state)}


def cmd_report(args) -> dict:
    state = _store(args).load()
    handoffs = Path(args.handoffs) if args.handoffs else _default_handoffs_dir(args)
    report = build_batch_report(
        state,
        handoffs_dir=handoffs if handoffs and handoffs.is_dir() else None,
    )
    markdown_path = Path(args.markdown) if args.markdown else None
    json_path = Path(args.json_path) if args.json_path else None
    if markdown_path is None and json_path is None:
        root = _root(args)
        stamp = state.updated_at.replace(":", "").replace("+", "")
        base = root / ".chatvector" / "issue-pipeline" / "reports" / f"batch-{stamp}"
        base.parent.mkdir(parents=True, exist_ok=True)
        markdown_path = base.with_suffix(".md")
        json_path = base.with_suffix(".json")
    written: dict[str, str] = {}
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
        written["markdown"] = str(markdown_path)
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written["json"] = str(json_path)
    return {
        "ok": True,
        "paths": written,
        "completion": report["completion"],
        "summary": (
            f"Batch report — {report['completion']['status']}: {report['completion']['summary']}"
        ),
    }


def cmd_lock(args) -> dict:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    code = run_locked(_suite_lock_path(_primary(args)), command, cwd=Path.cwd())
    return {"ok": code == 0, "exit_code": code}


def cmd_verify(args) -> dict:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    cwd = Path.cwd()
    if command_needs_lock(command):
        assert_migration_ledger_compatible(cwd)
    code, locked = run_verified(_suite_lock_path(_primary(args)), command, cwd=cwd)
    return {"ok": code == 0, "exit_code": code, "locked": locked}


def _bootstrap(state: BatchState, args) -> None:
    key = str(args.work or args.issue)
    if key in state.issues:
        return
    required = {
        "branch": args.branch,
        "reviewed_sha": args.reviewed_sha,
        "base_sha": args.base_sha,
        "worktree": args.worktree,
        "verification": args.verification,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise PipelineError(
            "init submit requires " + ", ".join(f"--{name.replace('_', '-')}" for name in missing),
            "publish",
        )
    number = int(key) if key.isdigit() else None
    state.issues[key] = IssueRecord(
        key=key,
        number=number,
        work_id=None if number is not None else key,
        title=args.title or key,
        summary=args.title or key,
        state="ready-to-publish",
        review_verdict="READY",
        reviewed_sha=args.reviewed_sha,
        base_sha=args.base_sha,
        head_sha=args.reviewed_sha,
        branch=args.branch,
        worktree=args.worktree,
        findings=args.findings or "none",
        verification=args.verification,
        mode="audit-fix" if args.audit_report or number is None else "issue",
        audit_report=args.audit_report,
    )
    state.event(key, "bootstrap", "ready-to-publish")


def _summary(state: BatchState) -> dict:
    issues = []
    for issue in sorted(state.issues.values(), key=lambda item: (item.queue_index, item.key)):
        issues.append(
            {
                "issue": issue.key,
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "pr": issue.pr_number,
                "branch": issue.branch,
                "worktree": issue.worktree,
                "base_sha": issue.base_sha,
                "reviewed_sha": issue.reviewed_sha,
                "merge_sha": issue.merge_sha,
                "merge_method": issue.merge_method,
                "model_slug": issue.model_slug,
                "claimed": issue.claimed,
                "worker_id": issue.worker_id,
                "worker_pid": issue.worker_pid,
                "hard_dependencies": issue.hard_dependencies,
                "soft_conflicts": issue.soft_conflicts,
                "blocker": issue.blocker,
                "reason_code": issue.reason_code,
                "fix_round": issue.fix_round,
                "external": issue.external,
                "mode": issue.mode,
            }
        )
    return {
        "concurrency": state.concurrency,
        "fallback": state.fallback,
        "review_model": state.review_model,
        "worker_mix": state.worker_mix,
        "effective_configuration": state.effective_config,
        "issues": issues,
        "events": state.events[-20:],
    }


def _load_snapshots(path: Path) -> dict[int, IssueSnapshot]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["issues"] if isinstance(data, dict) else data
    snapshots: dict[int, IssueSnapshot] = {}
    for item in items:
        labels = item.get("labels") or []
        if labels and isinstance(labels[0], dict):
            labels = [label.get("name", "") for label in labels]
        snapshot = IssueSnapshot(
            number=int(item["number"]),
            title=item.get("title") or "",
            body=item.get("body") or "",
            closed=bool(item.get("closed") or str(item.get("state") or "").lower() == "closed"),
            blocked_by=[int(number) for number in item.get("blocked_by") or []],
            labels=[str(label) for label in labels],
        )
        snapshots[snapshot.number] = snapshot
    return snapshots


def _root(args) -> Path:
    if args.repo:
        return Path(args.repo).resolve()
    return discover_main_checkout(Path.cwd())


def _primary(args) -> Path:
    """Primary checkout, even when --repo or cwd is a linked worktree."""

    start = _root(args)
    try:
        return discover_main_checkout(start)
    except PipelineError:
        return start


def _store(args, create: bool = False) -> StateStore:
    if args.state:
        path = Path(args.state)
    else:
        override = os.environ.get("PIPELINE_STATE_PATH")
        path = Path(override) if override else _root(args) / ".chatvector" / "issue-pipeline" / "state.json"
    store = StateStore(path)
    if create and not store.exists():
        store.save(BatchState())
    return store


def _git(args) -> GitRepo:
    return GitRepo(_root(args))


def _github(args) -> GitHubClient:
    git = _git(args)
    origin = git.run(["remote", "get-url", "origin"]).stdout.strip()
    upstream_proc = git.run(["remote", "get-url", "upstream"], check=False)
    upstream = upstream_proc.stdout.strip() if upstream_proc.returncode == 0 else None
    repos: RepoRef = resolve_from_urls(origin, upstream)
    return GitHubClient(repos, repo_root=_primary(args))


def _default_handoffs_dir(args) -> Path | None:
    root = _root(args)
    candidate = root / ".chatvector" / "issue-pipeline" / "handoffs"
    return candidate if candidate.is_dir() else None


def _merge_lock_path(root: Path) -> Path:
    return root / ".chatvector" / "issue-pipeline" / "locks" / "merge.lock"


def _suite_lock_path(root: Path) -> Path:
    return root / ".chatvector" / "issue-pipeline" / "locks" / "full-suite.json"


def _exit_code(exc: PipelineError) -> int:
    if exc.code in {"graph", "transition", "cleanup", "publish", "lock", "state", "handoff"}:
        return 2
    return 1


def _emit(payload: dict, code: int) -> int:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return code

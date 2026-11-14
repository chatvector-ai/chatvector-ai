"""Batch execution reports from pipeline state, events, and optional handoffs."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
    AI_ACTIVE,
    BLOCKED,
    IMPLEMENTING,
    MERGED,
    MERGING,
    NEEDS_FIX,
    PENDING_CI,
    QUEUED,
    READY,
    REVIEWING,
    BatchState,
    IssueRecord,
    occupies_slot,
)

_PHASE_EVENTS = {
    "claim": "worker",
    "ready-for-review": "implement",
    "ready-to-publish": "review",
    "needs-fix": "correction",
    "submitted": "publish",
    "ci-wait": "ci",
    "merging": "merge",
    "merged": "done",
    "implement-blocked": "blocked",
    "fix-limit": "blocked",
    "blocked": "blocked",
    "review-retry": "review",
    "premium-escalation": "escalation",
}

_QUEUE_REASON = {
    "missing-prerequisite": "dependency",
    "blocked-prerequisite": "dependency",
    "review-fix": "correction",
    "ci-failed": "ci",
    "fix-limit": "correction",
    "implement-blocked": "other",
}


def build_batch_report(
    state: BatchState,
    *,
    handoffs_dir: Path | None = None,
) -> dict[str, Any]:
    issues = _issue_reports(state)
    scheduling = _scheduling_report(state)
    metrics = _batch_metrics(state, issues)
    escalations = list(state.escalation_records)
    token_cost = {"available": False, "note": "token usage not recorded by issue-pipeline"}

    return {
        "generated_at": _now_iso(),
        "batch": {
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "concurrency": state.concurrency,
            "fallback": state.fallback,
            "orchestrator_id": state.orchestrator_id,
            "review_model": state.review_model,
            "worker_mix": state.worker_mix,
            "max_fix_rounds": state.max_fix_rounds,
            "escalation": {
                "enabled": state.escalation_enabled,
                "premium_slug": state.escalation_premium_slug,
                "batch_escalations_used": state.escalation_batch_count,
                "max_per_batch": state.escalation_max_per_batch,
            },
        },
        "completion": _completion_status(state),
        "scheduling": scheduling,
        "metrics": metrics,
        "issues": issues,
        "escalations": escalations,
        "token_cost": token_cost,
        "handoffs": _load_handoffs(handoffs_dir, state) if handoffs_dir else {},
        "events_truncated": len(state.events) >= 2000,
        "diagrams": {
            "ascii_timeline": render_ascii_timeline(scheduling.get("issue_phases") or {}),
            "mermaid_gantt": render_mermaid_gantt(scheduling.get("issue_phases") or {}),
        },
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    batch = report["batch"]
    metrics = report["metrics"]
    scheduling = report["scheduling"]
    lines = [
        "# Issue pipeline batch report",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Batch window: `{batch['created_at']}` → `{batch['updated_at']}`",
        f"Status: **{report['completion']['status']}** — {report['completion']['summary']}",
        "",
        "## Batch metrics",
        "",
        f"- Completion rate: **{metrics['completion_rate']:.0%}** ({metrics['merged']}/{metrics['total_issues']})",
        f"- First-pass review rate: **{metrics['first_pass_review_rate']:.0%}**",
        f"- Correction rounds (total): **{metrics['correction_rounds']}**",
        f"- Premium escalations: **{metrics['premium_escalations']}** (budget {batch['escalation']['max_per_batch']})",
        f"- CI failure episodes: **{metrics['ci_failure_episodes']}**",
        f"- Peak worker concurrency: **{scheduling.get('peak_concurrency', 0)}**",
        f"- Throughput: **{metrics['throughput_issues_per_hour']:.2f}** issues/hour (merged only)",
        f"- Token/cost data: **{report['token_cost']['note']}**",
        "",
        "## Scheduling and concurrency",
        "",
        f"- Initial execution waves: {', '.join('[' + ', '.join(w) + ']' for w in scheduling.get('waves') or [])}",
        f"- Concurrent launch at slot release: {', '.join(scheduling.get('concurrent_launches') or []) or '—'}",
        f"- Sequential fallback: `{batch.get('fallback') or 'none'}`",
        "",
        "### Queue waits",
        "",
        _markdown_table(
            ["Issue", "Queued until start", "Queue reason", "Deps satisfied"],
            [
                [
                    row["issue"],
                    row.get("queued_until_start") or "—",
                    row.get("queue_reason") or "—",
                    row.get("dependency_satisfied_at") or "—",
                ]
                for row in scheduling.get("queue_waits") or []
            ],
        ),
        "",
        "### Timeline",
        "",
        "```",
        report["diagrams"]["ascii_timeline"],
        "```",
        "",
        "### Mermaid Gantt",
        "",
        "```mermaid",
        report["diagrams"]["mermaid_gantt"],
        "```",
        "",
        "## Per-issue",
        "",
    ]

    for issue in report["issues"]:
        lines.extend(
            [
                f"### #{issue['number'] or issue['key']} — {issue['title']}",
                "",
                f"- GitHub: issue #{issue['number'] or '—'}, PR {issue.get('pr') or '—'}",
                f"- Final status: **{issue['state']}**"
                + (f", merge SHA `{issue['merge_sha'][:12]}…`" if issue.get("merge_sha") else ""),
                f"- Durations — implement: {issue['durations'].get('implement') or '—'}, "
                f"review: {issue['durations'].get('review') or '—'}, "
                f"fix: {issue['durations'].get('fix') or '—'}, "
                f"CI: {issue['durations'].get('ci') or '—'}, "
                f"total: {issue['durations'].get('total') or '—'}",
                f"- Model requested: `{issue.get('model_requested') or 'composer-inherit'}`; "
                f"confirmed: `{issue.get('model_confirmed') or 'unavailable'}`",
                f"- Review passes: **{issue['review_pass_count']}**; fix attempts: **{issue['fix_round']}**",
                f"- Findings — recurring: {len(issue.get('recurring_findings') or [])}, "
                f"new: {len(issue.get('new_findings') or [])}",
                f"- CI failures: {len(issue.get('ci_failures') or [])}",
                f"- Blocker: {issue.get('blocker') or 'none'} ({issue.get('reason_code') or '—'})",
                "",
            ]
        )
        if issue.get("review_history"):
            lines.append("Review history:")
            for entry in issue["review_history"]:
                lines.append(
                    f"- `{entry.get('at')}` verdict **{entry.get('verdict')}**"
                    f" — recurring {entry.get('recurring_count', 0)}, new {entry.get('new_count', 0)}"
                )
            lines.append("")

    if report.get("escalations"):
        lines.extend(["## Escalations", ""])
        for item in report["escalations"]:
            lines.append(
                f"- **{item.get('issue', '?')}**: {item.get('original_model')} → "
                f"`{item.get('escalated_model')}` — verified={item.get('slug_verified')}, "
                f"result={item.get('result')}, reviewer={item.get('reviewer_verdict') or '—'}"
            )
        lines.append("")

    if report.get("events_truncated"):
        lines.append(
            "> Event log was truncated in state storage; durations use available events only.\n"
        )

    return "\n".join(lines).rstrip() + "\n"


def render_ascii_timeline(phases: dict[str, list[dict]]) -> str:
    if not phases:
        return "(no phase data)"
    width = 48
    start = min(_parse_ts(p["start"]) for items in phases.values() for p in items if p.get("start"))
    end = max(_parse_ts(p["end"]) for items in phases.values() for p in items if p.get("end"))
    span = max(1.0, (end - start).total_seconds())
    lines: list[str] = []
    for key in sorted(phases, key=lambda k: (int(k) if k.isdigit() else 99999, k)):
        bar = [" "] * width
        for phase in phases[key]:
            phase_start = _parse_ts(phase["start"])
            phase_end = _parse_ts(phase["end"])
            left = int((phase_start - start).total_seconds() / span * width)
            right = max(left, int((phase_end - start).total_seconds() / span * width))
            glyph = phase.get("glyph", ".")
            for idx in range(max(0, left), min(width, right + 1)):
                bar[idx] = glyph
        lines.append(f"{key:>6} |{''.join(bar)}| {phases[key][0].get('label', '')}")
    return "\n".join(lines)


def render_mermaid_gantt(phases: dict[str, list[dict]]) -> str:
    lines = ["gantt", "    dateFormat HH:mm:ss", "    axisFormat %H:%M"]
    for key in sorted(phases, key=lambda k: (int(k) if k.isdigit() else 99999, k)):
        lines.append(f"    section Issue {key}")
        for phase in phases[key]:
            title = phase.get("phase", "phase")
            start = phase["start"][11:19]
            end = phase["end"][11:19]
            lines.append(f"    {title} :{title.replace(' ', '_')}, {start}, {end}")
    return "\n".join(lines)


def _scheduling_report(state: BatchState) -> dict[str, Any]:
    waves = _dependency_waves(state)
    phase_map = _reconstruct_phases(state)
    peak, samples = _peak_concurrency(state)
    queue_waits = _queue_waits(state, phase_map)
    launches = _concurrent_launches(state)
    return {
        "waves": waves,
        "dependency_graph": {
            key: list(issue.hard_dependencies)
            for key, issue in sorted(state.issues.items())
            if not issue.external
        },
        "peak_concurrency": peak,
        "concurrency_samples": samples,
        "concurrent_launches": launches,
        "queue_waits": queue_waits,
        "issue_phases": phase_map,
    }


def _issue_reports(state: BatchState) -> list[dict[str, Any]]:
    phase_map = _reconstruct_phases(state)
    reports: list[dict[str, Any]] = []
    for issue in sorted(state.issues.values(), key=lambda item: (item.queue_index, item.key)):
        if issue.external:
            continue
        phases = phase_map.get(issue.key, [])
        durations = _durations_from_phases(phases, state.created_at, state.updated_at)
        recurring: list[str] = []
        new: list[str] = []
        for entry in issue.review_history:
            recurring.extend(entry.get("recurring") or [])
            new.extend(entry.get("new") or [])
        reports.append(
            {
                "key": issue.key,
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "pr": issue.pr_number,
                "pr_url": issue.pr_url,
                "merge_sha": issue.merge_sha,
                "branch": issue.branch,
                "model_requested": issue.model_slug,
                "model_confirmed": issue.model_confirmed,
                "fix_round": issue.fix_round,
                "review_pass_count": len(issue.review_history),
                "review_history": issue.review_history,
                "recurring_findings": sorted(set(recurring)),
                "new_findings": sorted(set(new)),
                "verification": issue.verification,
                "ci_failures": issue.ci_failures,
                "blocker": issue.blocker,
                "reason_code": issue.reason_code,
                "durations": durations,
                "escalation_records": issue.escalation_records,
                "premium_attempts": issue.premium_attempts,
            }
        )
    return reports


def _batch_metrics(state: BatchState, issues: list[dict]) -> dict[str, Any]:
    total = len(issues)
    merged = sum(1 for item in issues if item["state"] == MERGED)
    first_pass = sum(
        1
        for item in issues
        if item["state"] == MERGED and item["fix_round"] == 0 and item["review_pass_count"] <= 1
    )
    correction_rounds = sum(item["fix_round"] for item in issues)
    premium = sum(len(item.get("escalation_records") or []) for item in issues)
    ci_eps = sum(len(item.get("ci_failures") or []) for item in issues)
    elapsed = max(0.0, (_parse_ts(state.updated_at) - _parse_ts(state.created_at)).total_seconds())
    throughput = (merged / elapsed * 3600) if elapsed and merged else 0.0
    return {
        "total_issues": total,
        "merged": merged,
        "blocked": sum(1 for item in issues if item["state"] == BLOCKED),
        "completion_rate": merged / total if total else 0.0,
        "first_pass_review_rate": first_pass / total if total else 0.0,
        "correction_rounds": correction_rounds,
        "premium_escalations": premium,
        "ci_failure_episodes": ci_eps,
        "throughput_issues_per_hour": throughput,
    }


def _completion_status(state: BatchState) -> dict[str, str]:
    active = [
        issue.key
        for issue in state.issues.values()
        if not issue.external and issue.state not in {MERGED, BLOCKED}
    ]
    if active:
        return {
            "status": "partial",
            "summary": f"{len(active)} issue(s) still active: {', '.join(active)}",
        }
    blocked = [issue.key for issue in state.issues.values() if issue.state == BLOCKED]
    merged = [issue.key for issue in state.issues.values() if issue.state == MERGED]
    if blocked and merged:
        return {
            "status": "partial",
            "summary": f"merged {len(merged)}, blocked {len(blocked)}",
        }
    if blocked:
        return {"status": "blocked", "summary": f"all remaining issues blocked ({len(blocked)})"}
    return {"status": "complete", "summary": f"all {len(merged)} issues merged"}


def _dependency_waves(state: BatchState) -> list[list[str]]:
    nodes = {
        key: set(issue.hard_dependencies)
        for key, issue in state.issues.items()
        if not issue.external
    }
    waves: list[list[str]] = []
    remaining = set(nodes)
    satisfied: set[str] = {
        key for key, issue in state.issues.items() if issue.external and issue.state == MERGED
    }
    while remaining:
        ready = sorted(
            key
            for key in remaining
            if nodes[key].issubset(satisfied | {k for k, i in state.issues.items() if i.external})
        )
        if not ready:
            ready = [sorted(remaining, key=lambda k: (state.issues[k].queue_index, k))[0]]
        waves.append(ready)
        satisfied.update(ready)
        remaining -= set(ready)
    return waves


def _reconstruct_phases(state: BatchState) -> dict[str, list[dict]]:
    """Build per-issue phase intervals from the event log."""

    glyphs = {
        "implement": "I",
        "review": "R",
        "correction": "F",
        "ci": "C",
        "merge": "M",
        "blocked": "X",
        "escalation": "P",
    }
    open_phase: dict[str, tuple[str, str]] = {}
    result: dict[str, list[dict]] = defaultdict(list)

    def close(issue_key: str, end_at: str) -> None:
        if issue_key not in open_phase:
            return
        phase, start_at = open_phase.pop(issue_key)
        result[issue_key].append(
            {
                "phase": phase,
                "start": start_at,
                "end": end_at,
                "glyph": glyphs.get(phase, "."),
                "label": phase,
            }
        )

    def open(issue_key: str, phase: str, start_at: str) -> None:
        close(issue_key, start_at)
        open_phase[issue_key] = (phase, start_at)

    for event in state.events:
        issue_key = event.get("issue")
        if not issue_key:
            continue
        name = event.get("event") or ""
        at = event.get("at") or state.updated_at
        if name == "claim":
            detail = event.get("detail") or ""
            if detail.startswith("implement"):
                open(issue_key, "implement", at)
            elif detail.startswith("review"):
                open(issue_key, "review", at)
        elif name == "ready-for-review":
            close(issue_key, at)
            open(issue_key, "review", at)
        elif name in {"ready-to-publish", "review-retry"}:
            close(issue_key, at)
        elif name == "needs-fix":
            close(issue_key, at)
            open(issue_key, "correction", at)
        elif name == "submitted":
            close(issue_key, at)
            open(issue_key, "ci", at)
        elif name == "merging":
            close(issue_key, at)
            open(issue_key, "merge", at)
        elif name == "merged":
            close(issue_key, at)
        elif name in {"fix-limit", "implement-blocked", "blocked", "review-malformed"}:
            close(issue_key, at)
            open(issue_key, "blocked", at)
        elif name == "premium-escalation":
            result[issue_key].append(
                {
                    "phase": "escalation",
                    "start": at,
                    "end": at,
                    "glyph": "P",
                    "label": "premium scheduled",
                }
            )

    for issue_key in open_phase:
        close(issue_key, state.updated_at)

    return dict(result)


def _peak_concurrency(state: BatchState) -> tuple[int, list[dict]]:
    active: set[str] = set()
    peak = 0
    samples: list[dict] = []
    for event in state.events:
        issue_key = event.get("issue")
        name = event.get("event") or ""
        at = event.get("at")
        if not issue_key:
            continue
        if name == "claim":
            active.add(issue_key)
        elif name in {
            "ready-for-review",
            "ready-to-publish",
            "needs-fix",
            "implement-blocked",
            "fix-limit",
            "blocked",
            "review-malformed",
            "merged",
        }:
            issue = state.issues.get(issue_key)
            if issue and occupies_slot(issue, state.concurrency):
                active.discard(issue_key)
        peak = max(peak, len(active))
        if name == "claim":
            samples.append({"at": at, "active": sorted(active), "count": len(active)})
    return peak, samples


def _queue_waits(state: BatchState, phases: dict[str, list[dict]]) -> list[dict]:
    rows: list[dict] = []
    for issue in sorted(state.issues.values(), key=lambda item: (item.queue_index, item.key)):
        if issue.external:
            continue
        first_start = None
        for phase in phases.get(issue.key, []):
            if phase["phase"] == "implement":
                first_start = phase["start"]
                break
        dep_at = _first_event(state, issue.key, "unblocked")
        reason = "worker capacity"
        if issue.hard_dependencies and not dep_at:
            reason = "dependency"
        elif issue.reason_code in _QUEUE_REASON:
            reason = _QUEUE_REASON[issue.reason_code]
        rows.append(
            {
                "issue": issue.key,
                "queued_until_start": _duration(state.created_at, first_start),
                "queue_reason": reason,
                "dependency_satisfied_at": dep_at,
            }
        )
    return rows


def _concurrent_launches(state: BatchState) -> list[str]:
    groups: list[str] = []
    current: list[str] = []
    last_at: str | None = None
    for event in state.events:
        if event.get("event") != "claim":
            continue
        if not (event.get("detail") or "").startswith("implement"):
            continue
        at = event.get("at")
        if last_at and at and (_parse_ts(at) - _parse_ts(last_at)).total_seconds() > 2:
            if len(current) > 1:
                groups.append(", ".join(current))
            current = []
        last_at = at
        if event.get("issue"):
            current.append(str(event["issue"]))
    if len(current) > 1:
        groups.append(", ".join(current))
    return groups


def _durations_from_phases(phases: list[dict], created: str, updated: str) -> dict[str, str | None]:
    totals: dict[str, float] = defaultdict(float)
    for phase in phases:
        name = phase.get("phase") or ""
        start = _parse_ts(phase["start"])
        end = _parse_ts(phase["end"])
        totals[name] += max(0.0, (end - start).total_seconds())
    if phases:
        total = (_parse_ts(phases[-1]["end"]) - _parse_ts(phases[0]["start"])).total_seconds()
    else:
        total = (_parse_ts(updated) - _parse_ts(created)).total_seconds()
    return {
        "implement": _fmt_seconds(totals.get("implement", 0.0)),
        "review": _fmt_seconds(totals.get("review", 0.0)),
        "fix": _fmt_seconds(totals.get("correction", 0.0)),
        "ci": _fmt_seconds(totals.get("ci", 0.0)),
        "total": _fmt_seconds(max(0.0, total)),
    }


def _load_handoffs(handoffs_dir: Path, state: BatchState) -> dict[str, list[str]]:
    if not handoffs_dir.is_dir():
        return {}
    loaded: dict[str, list[str]] = {}
    for key in state.issues:
        paths: list[Path] = []
        for pattern in (f"{key}-*.md", f"{key}-*.txt"):
            paths.extend(handoffs_dir.glob(pattern))
        if paths:
            loaded[key] = [str(path) for path in sorted({p.resolve() for p in paths})]
    return loaded


def _first_event(state: BatchState, issue_key: str, name: str) -> str | None:
    for event in state.events:
        if event.get("issue") == issue_key and event.get("event") == name:
            return event.get("at")
    return None


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "| (none) |"
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([head, sep, *body])


def _duration(start: str | None, end: str | None) -> str | None:
    if not start or not end:
        return None
    return _fmt_seconds(max(0.0, (_parse_ts(end) - _parse_ts(start)).total_seconds()))


def _fmt_seconds(value: float) -> str | None:
    if value <= 0:
        return None
    if value < 90:
        return f"{int(value)}s"
    minutes, seconds = divmod(int(value), 60)
    if minutes < 90:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()

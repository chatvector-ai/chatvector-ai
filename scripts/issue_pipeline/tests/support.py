"""Shared helpers for pipeline tests. Queue parsing ignores the developer environment."""

from __future__ import annotations

from pathlib import Path

from scripts.issue_pipeline.dependencies import IssueSnapshot, build_batch
from scripts.issue_pipeline.queue import parse_queue


def snapshot(
    number: int,
    title: str = "",
    body: str = "",
    *,
    closed: bool = False,
    blocked_by: list[int] | None = None,
    labels: list[str] | None = None,
) -> IssueSnapshot:
    return IssueSnapshot(
        number=number,
        title=title or f"Issue {number}",
        body=body,
        closed=closed,
        blocked_by=blocked_by or [],
        labels=labels or [],
    )


def plan(
    text: str,
    issues: list[IssueSnapshot],
    *,
    closed: set[int] | None = None,
    env: dict | None = None,
    repo_root: Path | None = None,
):
    snaps = {item.number: item for item in issues}
    return build_batch(
        parse_queue(text, env or {}),
        snaps,
        closed_numbers=closed,
        repo_root=repo_root,
    )

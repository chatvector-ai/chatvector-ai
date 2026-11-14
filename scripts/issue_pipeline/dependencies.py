"""Hard dependencies versus soft integration conflicts.

Explicit issue text, batch annotations, GitHub blocked-by links, and an epic
batch-order section become hard edges. Shared key files and "may conflict"
notes are recorded and do not delay the start of work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .batch_config import (
    apply_resolved_config,
    config_event_detail,
    resolve_batch_config,
)
from .models import (
    BLOCKED,
    MERGED,
    BatchState,
    GraphError,
    IssueRecord,
)
from .queue import ParsedQueue, QueueItem, assign_models

_HARD_LINE = re.compile(
    r"(depends on|blocked by|requires|prerequisite|builds on|follow-?up to|part \d+ of|\bafter\b)",
    re.I,
)
_SOFT_LINE = re.compile(
    r"(may conflict with|integration conflict|same files as|same api as)",
    re.I,
)
_TASK_LINE = re.compile(r"(?m)^[ \t]*- \[[ xX]\]")


@dataclass
class IssueSnapshot:
    number: int
    title: str = ""
    body: str = ""
    closed: bool = False
    blocked_by: list[int] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


@dataclass
class EdgeSet:
    hard: dict[int, set[int]] = field(default_factory=dict)
    soft: dict[int, set[int]] = field(default_factory=dict)

    def add_hard(self, issue: int, dependency: int) -> None:
        if issue == dependency:
            raise GraphError(f"issue #{issue} depends on itself")
        self.hard.setdefault(issue, set()).add(dependency)

    def add_soft(self, issue: int, other: int) -> None:
        if issue == other:
            return
        self.soft.setdefault(issue, set()).add(other)
        self.soft.setdefault(other, set()).add(issue)


def section_body(text: str, heading: str) -> str | None:
    pattern = re.compile(rf"(?mi)^##\s+{re.escape(heading)}\s*$")
    match = pattern.search(text)
    if not match:
        return None
    rest = text[match.end() :]
    nxt = re.search(r"(?m)^##\s+", rest)
    if nxt:
        rest = rest[: nxt.start()]
    return rest


def numbers_in(text: str) -> list[int]:
    seen: list[int] = []
    for value in re.findall(r"#(\d+)", text):
        number = int(value)
        if number not in seen:
            seen.append(number)
    return seen


def child_numbers(body: str) -> list[int]:
    """Issue numbers listed under `## Child issues` (bullet lines only)."""

    section = section_body(body, "Child issues") or ""
    children: list[int] = []
    for line in section.splitlines():
        match = re.match(r"^\s*[-*]\s*#(\d+)\b", line)
        if match:
            number = int(match.group(1))
            if number not in children:
                children.append(number)
    return children


def is_epic(body: str) -> bool:
    children = section_body(body, "Child issues")
    if not children or not numbers_in(children):
        return False
    lowered = body.lower()
    tracking = (
        "tracking epic",
        "do not implement",
        "implementation lives in the child",
        "not implementable",
    )
    if any(marker in lowered for marker in tracking):
        return True
    if _TASK_LINE.search(body):
        return False
    return True


def key_files(body: str) -> set[str]:
    section = section_body(body, "Key files")
    if not section:
        return set()
    found = set(re.findall(r"`([^`]+)`", section))
    found.update(
        re.findall(
            r"(?m)^\s*-\s+([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)\s*$",
            section,
        )
    )
    return {item.strip() for item in found if item.strip()}


def edges_from_body(number: int, body: str, edges: EdgeSet) -> None:
    for line in body.splitlines():
        numbers = [int(value) for value in re.findall(r"#(\d+)", line)]
        if not numbers:
            continue
        if _HARD_LINE.search(line):
            for dependency in numbers:
                edges.add_hard(number, dependency)
        elif _SOFT_LINE.search(line):
            for other in numbers:
                edges.add_soft(number, other)
    order = section_body(body, "Batch order")
    if order:
        sequence = numbers_in(order)
        for earlier, later in zip(sequence, sequence[1:]):
            edges.add_hard(later, earlier)


def find_cycle(nodes: dict[str, set[str]]) -> list[str] | None:
    color: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = 1
        stack.append(node)
        for dependency in nodes.get(node, ()):
            if dependency not in nodes:
                continue
            if color.get(dependency) == 1:
                start = stack.index(dependency)
                return stack[start:] + [dependency]
            if color.get(dependency) != 2:
                found = visit(dependency)
                if found:
                    return found
        stack.pop()
        color[node] = 2
        return None

    for node in list(nodes):
        if node not in color:
            found = visit(node)
            if found:
                return found
    return None


def collect_snapshots(parsed: ParsedQueue, fetch) -> dict[int, IssueSnapshot]:
    """Load every queued issue and, for epics, the child issues prepare will expand."""

    snapshots: dict[int, IssueSnapshot] = {}
    pending = [item.number for item in parsed.items]
    no_expand = {item.number for item in parsed.items if item.no_expand}
    while pending:
        number = pending.pop(0)
        if number in snapshots:
            continue
        snapshot = fetch(number)
        if snapshot.number != number:
            raise GraphError(f"fetcher returned #{snapshot.number} for #{number}")
        snapshots[number] = snapshot
        if number in no_expand or not is_epic(snapshot.body):
            continue
        for child in child_numbers(snapshot.body):
            if child not in snapshots:
                pending.append(child)
    return snapshots


def expand_items(
    items: list[QueueItem],
    snapshots: dict[int, IssueSnapshot],
) -> list[QueueItem]:
    expanded: list[QueueItem] = []
    for item in items:
        snapshot = snapshots.get(item.number)
        if snapshot is None:
            raise GraphError(f"missing issue snapshot for #{item.number}")
        if item.no_expand or not is_epic(snapshot.body):
            expanded.append(item)
            continue
        children = child_numbers(snapshot.body)
        if not children:
            raise GraphError(f"epic #{item.number} has no child issues")
        epic_edges = EdgeSet()
        edges_from_body(item.number, snapshot.body, epic_edges)
        parent_deps = list(item.hard_dependencies)
        for dep in epic_edges.hard.get(item.number, set()):
            if dep not in parent_deps:
                parent_deps.append(dep)
        order_deps: dict[int, list[int]] = {}
        order = section_body(snapshot.body, "Batch order")
        if order:
            sequence = numbers_in(order)
            for earlier, later in zip(sequence, sequence[1:]):
                order_deps.setdefault(later, []).append(earlier)
        for child in children:
            if child not in snapshots:
                raise GraphError(
                    f"epic #{item.number} lists #{child}, which has no snapshot"
                )
            child_deps = list(parent_deps)
            for dep in order_deps.get(child, []):
                if dep not in child_deps:
                    child_deps.append(dep)
            child_item = QueueItem(
                number=child,
                hard_dependencies=child_deps,
                prefix=item.prefix,
                no_expand=True,
                source=f"epic #{item.number}",
            )
            expanded.append(child_item)
    _reject_duplicates(expanded)
    return expanded


def build_batch(
    parsed: ParsedQueue,
    snapshots: dict[int, IssueSnapshot],
    *,
    closed_numbers: set[int] | None = None,
    repo_root: Path | None = None,
) -> BatchState:
    """Validate the graph and return a batch that has not been written yet."""

    closed = set(closed_numbers or ())
    for snapshot in snapshots.values():
        if snapshot.closed:
            closed.add(snapshot.number)

    items = expand_items(parsed.items, snapshots)
    assign_models(items, parsed)
    _reject_duplicates(items)

    numbers = {item.number for item in items}
    edges = EdgeSet()
    files: dict[int, set[str]] = {}
    for item in items:
        snapshot = snapshots[item.number]
        for dependency in item.hard_dependencies:
            edges.add_hard(item.number, dependency)
        for dependency in snapshot.blocked_by:
            edges.add_hard(item.number, dependency)
        edges_from_body(item.number, snapshot.body, edges)
        files[item.number] = key_files(snapshot.body)

    for left, left_files in files.items():
        for right, right_files in files.items():
            if left >= right:
                continue
            if left_files and right_files and left_files & right_files:
                edges.add_soft(left, right)

    graph = {str(number): {str(dep) for dep in edges.hard.get(number, set())} for number in numbers}
    cycle = find_cycle(graph)
    if cycle:
        raise GraphError("cyclic dependencies: " + " -> ".join(cycle))

    resolved = resolve_batch_config(
        repo_root=repo_root,
        queue_concurrency=parsed.concurrency,
        queue_max_fix_rounds=parsed.max_fix_rounds,
        queue_implementation_model=parsed.implementation_model,
        queue_review_model=parsed.review_model if parsed.review_model != "same" else None,
        queue_escalation_enabled=parsed.escalation_enabled,
        queue_escalation_premium=parsed.escalation_premium,
        queue_escalation_max_batch=parsed.escalation_max_batch,
        queue_escalation_max_per_issue=parsed.escalation_max_per_issue,
        queue_composer_attempts=parsed.composer_attempts_before_escalation,
    )
    state = BatchState(
        worker_mix=parsed.worker_mix,
        alternate_slug=parsed.alternate_slug,
        fallback=parsed.fallback,
    )
    apply_resolved_config(state, resolved)
    if parsed.review_model == "alternate":
        state.review_model = "alternate"
        state.review_model_slug = parsed.review_model_slug or parsed.alternate_slug
    elif parsed.review_model and parsed.review_model != "same":
        state.review_model = parsed.review_model
    state.event(None, "config-resolved", config_event_detail(resolved))

    referenced = set(numbers)
    for deps in edges.hard.values():
        referenced.update(deps)

    for number in sorted(referenced):
        if number in numbers:
            continue
        if number in closed:
            state.issues[str(number)] = IssueRecord(
                key=str(number),
                number=number,
                title="(already closed)",
                state=MERGED,
                external=True,
                queue_index=-1,
            )
            continue
        # The dependent is blocked below; no placeholder issue is invented.

    for index, item in enumerate(items):
        snapshot = snapshots[item.number]
        hard = sorted(str(dep) for dep in edges.hard.get(item.number, set()))
        soft = sorted(
            str(other)
            for other in edges.soft.get(item.number, set())
            if other in numbers
        )
        record = IssueRecord(
            key=str(item.number),
            number=item.number,
            title=snapshot.title,
            queue_index=index,
            hard_dependencies=hard,
            soft_conflicts=soft,
            model_slug=item.model_slug,
            queue_prefix=item.prefix,
            issue_model_override=item.issue_model,
            escalation_disabled=item.escalation_disabled is True,
            summary=snapshot.title,
        )
        if item.number in closed or snapshot.closed:
            record.state = MERGED
            record.external = True
            record.notes = "closed before the batch started"
        else:
            missing = [
                dep
                for dep in hard
                if dep not in state.issues and dep not in {str(n) for n in numbers}
            ]
            # `state.issues` does not yet include later batch issues. Check the
            # batch set and the external closed set instead.
            missing = [
                dep
                for dep in hard
                if int(dep) not in numbers and int(dep) not in closed
            ]
            if missing:
                record.state = BLOCKED
                record.reason_code = "missing-prerequisite"
                record.blocker = "missing prerequisite " + ", ".join(
                    f"#{dep}" for dep in missing
                )
        state.issues[record.key] = record

    _cascade_blocked(state)
    state.event(
        None,
        "prepared",
        f"concurrency={state.concurrency} fallback={state.fallback or 'none'}",
    )
    return state


def _reject_duplicates(items: list[QueueItem]) -> None:
    seen: dict[int, QueueItem] = {}
    for item in items:
        previous = seen.get(item.number)
        if previous is not None:
            raise GraphError(
                f"duplicate issue #{item.number} ({previous.source or 'queue'} and {item.source or 'queue'})"
            )
        seen[item.number] = item


def _cascade_blocked(state: BatchState) -> None:
    changed = True
    while changed:
        changed = False
        for issue in state.issues.values():
            if issue.external or issue.state != "queued":
                continue
            for dep in issue.hard_dependencies:
                other = state.issues.get(dep)
                if other is not None and other.state == BLOCKED:
                    issue.state = BLOCKED
                    issue.reason_code = "blocked-prerequisite"
                    issue.blocker = f"prerequisite #{dep} is blocked"
                    changed = True
                    break


cascade_blocked = _cascade_blocked

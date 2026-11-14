"""Scheduling telemetry derived from explicit state-transition events."""

from __future__ import annotations

from .models import QUEUED, IssueRecord


def deps_satisfied(issue: IssueRecord, issues: dict[str, IssueRecord]) -> bool:
    from .models import MERGED

    for dep in issue.hard_dependencies:
        other = issues.get(dep)
        if other is None or other.state != MERGED:
            return False
    return True


def deps_satisfied_record(state, issue: IssueRecord) -> None:
    if issue.deps_satisfied_at:
        return
    if not deps_satisfied(issue, state.issues):
        return
    issue.deps_satisfied_at = state.updated_at
    if issue.state == QUEUED:
        issue.eligible_at = issue.eligible_at or state.updated_at
        state.event(issue.key, "deps-satisfied", "")
        if issue.capacity_wait_since:
            state.event(issue.key, "capacity-available", "dependency path")
    note_capacity_waiters(state)


def mark_queued_schedule(state, issue: IssueRecord) -> None:
    if issue.external or issue.state != QUEUED:
        return
    if issue.hard_dependencies and not deps_satisfied(issue, state.issues):
        if not issue.waiting_deps_since:
            issue.waiting_deps_since = state.updated_at
            detail = "deps=" + ",".join(issue.hard_dependencies)
            state.event(issue.key, "wait-deps", detail)
        return
    issue.waiting_deps_since = None
    issue.eligible_at = issue.eligible_at or state.updated_at
    state.event(issue.key, "eligible", "")
    note_capacity_waiters(state)


def note_capacity_waiters(state) -> None:
    from .scheduler import occupies_slot, slots_used

    free = max(0, state.concurrency - slots_used(state))
    if free <= 0:
        for issue in _ordered(state):
            if issue.external or issue.claimed:
                continue
            if issue.state != QUEUED or not deps_satisfied(issue, state.issues):
                continue
            if not issue.capacity_wait_since:
                issue.capacity_wait_since = state.updated_at
                state.event(issue.key, "wait-capacity", f"slots={state.concurrency}")
    else:
        for issue in _ordered(state):
            if issue.capacity_wait_since and issue.state == QUEUED and not issue.claimed:
                state.event(issue.key, "capacity-available", f"slots_free={free}")
                issue.capacity_wait_since = None


def worker_start(
    state,
    issue: IssueRecord,
    *,
    action: str,
    worker_id: str,
    requested_model: str | None,
) -> None:
    issue.capacity_wait_since = None
    issue.waiting_deps_since = None
    phase = "implement" if action == "implement" else "review"
    issue.worker_started_at = state.updated_at
    selection = requested_model or "composer-inherit"
    state.event(issue.key, "worker-start", f"{phase} worker={worker_id} model={selection}")
    issue.worker_runs.append(
        {
            "at": state.updated_at,
            "phase": phase,
            "worker_id": worker_id,
            "requested_model": selection,
            "confirmed_model": None,
            "model_verified": "requested-unverified",
            "task_id": None,
        }
    )


def worker_release(state, issue: IssueRecord, *, detail: str) -> None:
    state.event(issue.key, "worker-release", detail)
    issue.worker_started_at = None
    note_capacity_waiters(state)


def phase_transition(state, issue: IssueRecord, phase: str, detail: str = "") -> None:
    state.event(issue.key, "phase", f"{phase} {detail}".strip())


def ci_pending(state, issue: IssueRecord, detail: str = "") -> None:
    state.event(issue.key, "ci-pending", detail)


def ci_complete(state, issue: IssueRecord, detail: str) -> None:
    state.event(issue.key, "ci-complete", detail)


def record_worker_model(
    issue: IssueRecord,
    *,
    phase: str,
    task_id: str,
    requested_model: str | None,
    confirmed_model: str | None,
    verified: str,
) -> None:
    entry = None
    for run in reversed(issue.worker_runs):
        if run.get("phase") == phase and run.get("task_id") is None:
            entry = run
            break
    if entry is None:
        entry = {
            "at": None,
            "phase": phase,
            "worker_id": issue.worker_id,
            "requested_model": requested_model or "composer-inherit",
            "confirmed_model": None,
            "model_verified": "requested-unverified",
            "task_id": None,
        }
        issue.worker_runs.append(entry)
    entry["task_id"] = task_id
    if requested_model:
        entry["requested_model"] = requested_model
    entry["confirmed_model"] = confirmed_model
    entry["model_verified"] = verified
    if confirmed_model and verified == "yes":
        issue.model_confirmed = confirmed_model
    elif verified in {"no", "unknown"} and not issue.model_confirmed:
        issue.model_confirmed = "requested-unverified"


def requested_model_for_action(state, issue: IssueRecord, action: str) -> str | None:
    if action == "review":
        slug = state.review_model_slug
        if slug:
            return slug
    if issue.model_slug:
        return issue.model_slug
    if action == "implement":
        return getattr(state, "implementation_model_slug", None) or "composer-inherit"
    return getattr(state, "implementation_model_slug", None) or "composer-inherit"


def _ordered(state) -> list[IssueRecord]:
    return sorted(state.issues.values(), key=lambda item: (item.queue_index, item.key))

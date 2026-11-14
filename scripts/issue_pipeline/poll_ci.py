"""Poll GitHub CI and squash-merge until pending-ci issues finish or need an agent."""

from __future__ import annotations

import os
import time
from typing import Any

from .models import BLOCKED, NEEDS_FIX, PENDING_CI, BatchState
from .publisher import tick
from .state import StateStore


def _poll_interval() -> float:
    raw = os.environ.get("PIPELINE_CI_POLL_INTERVAL", "15")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"PIPELINE_CI_POLL_INTERVAL must be a number, got {raw!r}") from exc
    return max(5.0, value)


def _poll_max_wait() -> float:
    raw = os.environ.get("PIPELINE_CI_POLL_MAX_WAIT", "1800")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"PIPELINE_CI_POLL_MAX_WAIT must be a number, got {raw!r}") from exc
    return max(60.0, value)


def pending_ci_keys(state: BatchState) -> list[str]:
    return sorted(
        key
        for key, issue in state.issues.items()
        if issue.state == PENDING_CI and issue.pr_number
    )


def poll_ci(
    store: StateStore,
    git,
    hub,
    *,
    lock_path,
    suite_lock_path,
    only: str | None = None,
    interval: float | None = None,
    max_wait: float | None = None,
) -> dict[str, Any]:
    """Run ``tick`` on pending-ci issues until done, timed out, or an agent is needed."""

    wait_interval = interval if interval is not None else _poll_interval()
    deadline = time.monotonic() + (max_wait if max_wait is not None else _poll_max_wait())
    rounds = 0
    tick_history: list[dict] = []
    merged: list[dict] = []

    while time.monotonic() < deadline:
        with store.transaction() as state:
            keys = pending_ci_keys(state)
            if only is not None:
                keys = [str(only)] if str(only) in keys else []
            if not keys:
                return {
                    "ok": True,
                    "done": True,
                    "reason": "no pending-ci pull requests",
                    "rounds": rounds,
                    "merged": merged,
                    "ticks": tick_history,
                }

        tick_result = tick(
            store,
            git,
            hub,
            lock_path=lock_path,
            suite_lock_path=suite_lock_path,
            only=only,
        )
        rounds += 1
        tick_history.append(tick_result)

        for item in tick_result.get("results") or []:
            if item.get("action") == "merged":
                merged.append(item)

        agent_required = _agent_required(store, only=only)
        if agent_required:
            return {
                "ok": True,
                "done": False,
                "reason": "agent_required",
                "detail": agent_required,
                "rounds": rounds,
                "merged": merged,
                "ticks": tick_history[-1:],
            }

        with store.transaction() as state:
            if not pending_ci_keys(state) or (
                only is not None and str(only) not in pending_ci_keys(state)
            ):
                return {
                    "ok": True,
                    "done": True,
                    "reason": "pending-ci cleared",
                    "rounds": rounds,
                    "merged": merged,
                    "ticks": tick_history[-1:],
                }

        if time.monotonic() >= deadline:
            break
        time.sleep(wait_interval)

    with store.transaction() as state:
        remaining = pending_ci_keys(state)
        if only is not None:
            remaining = [k for k in remaining if k == str(only)]

    return {
        "ok": True,
        "done": False,
        "reason": "timeout",
        "remaining": remaining,
        "rounds": rounds,
        "merged": merged,
        "ticks": tick_history[-3:],
    }


def _agent_required(store: StateStore, *, only: str | None) -> str | None:
    with store.transaction() as state:
        for key, issue in state.issues.items():
            if only is not None and key != str(only):
                continue
            if issue.state == NEEDS_FIX:
                kind = issue.correction_kind or "implement"
                return f"issue {key} is needs-fix ({kind})"
            if issue.state == BLOCKED:
                return f"issue {key} is blocked: {issue.blocker or issue.reason_code}"
    return None
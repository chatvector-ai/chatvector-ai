"""State records and legal transitions for one batch."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

QUEUED = "queued"
IMPLEMENTING = "implementing"
REVIEWING = "reviewing"
NEEDS_FIX = "needs-fix"
READY = "ready-to-publish"
PENDING_CI = "pending-ci"
MERGING = "merging"
MERGED = "merged"
BLOCKED = "blocked"

# Implementation and review occupy an AI worker. CI wait does not.
AI_ACTIVE = {IMPLEMENTING, REVIEWING, NEEDS_FIX}
# Sequential mode also holds the single slot through publish and CI.
SEQUENTIAL_BUSY = AI_ACTIVE | {READY, PENDING_CI, MERGING}

ALLOWED: dict[str, set[str]] = {
    QUEUED: {IMPLEMENTING, BLOCKED, MERGED},
    IMPLEMENTING: {REVIEWING, BLOCKED},
    REVIEWING: {READY, NEEDS_FIX, BLOCKED, REVIEWING},
    NEEDS_FIX: {IMPLEMENTING, REVIEWING, BLOCKED},
    READY: {PENDING_CI, BLOCKED},
    PENDING_CI: {MERGING, NEEDS_FIX, BLOCKED, PENDING_CI, MERGED},
    MERGING: {MERGED, PENDING_CI, BLOCKED},
    MERGED: set(),
    BLOCKED: {QUEUED, PENDING_CI, NEEDS_FIX},
}

STATE_VERSION = 1


class PipelineError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


class GraphError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, "graph")


class TransitionError(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, "transition")


class PublishError(PipelineError):
    def __init__(self, message: str, code: str = "publish"):
        super().__init__(message, code)


class CleanupRefused(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, "cleanup")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class IssueRecord:
    key: str
    number: int | None = None
    work_id: str | None = None
    title: str = ""
    state: str = QUEUED
    queue_index: int = 0
    hard_dependencies: list[str] = field(default_factory=list)
    soft_conflicts: list[str] = field(default_factory=list)
    branch: str | None = None
    worktree: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    reviewed_sha: str | None = None
    review_verdict: str | None = None
    findings: str | None = None
    verification: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    integration_base_sha: str | None = None
    integration_result: str | None = None
    integration_correction_round: int = 0
    upstream_base_sha: str | None = None
    upstream_invalidation_count: int = 0
    rebase_authorized: bool = False
    last_failure_category: str | None = None
    failure_records: list[dict] = field(default_factory=list)
    merge_sha: str | None = None
    merge_method: str | None = None
    primary_sync: dict | None = None
    model_slug: str | None = None
    worker_pid: int | None = None
    worker_id: str | None = None
    claimed: bool = False
    interrupted: bool = False
    fix_round: int = 0
    review_malformed: int = 0
    correction_kind: str | None = None
    handoff_status: str | None = None
    blocker: str | None = None
    reason_code: str | None = None
    mode: str = "issue"
    audit_report: str | None = None
    summary: str | None = None
    ci_failures: list[dict] = field(default_factory=list)
    queue_prefix: str | None = None
    issue_model_override: str | None = None
    escalation_disabled: bool = False
    premium_pending: bool = False
    premium_attempts: int = 0
    last_implement_premium: bool = False
    model_confirmed: str | None = None
    eligible_at: str | None = None
    deps_satisfied_at: str | None = None
    waiting_deps_since: str | None = None
    capacity_wait_since: str | None = None
    worker_started_at: str | None = None
    worker_runs: list[dict] = field(default_factory=list)
    last_review_findings: str | None = None
    review_history: list[dict] = field(default_factory=list)
    escalation_records: list[dict] = field(default_factory=list)
    operator_rescue_at: str | None = None
    blocked_idle_since: str | None = None
    missing_polls: int = 0
    tasks_checked: str | None = None
    areas: list[str] = field(default_factory=list)
    external: bool = False
    pushed_sha: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> IssueRecord:
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass
class BatchState:
    version: int = STATE_VERSION
    concurrency: int = 3
    max_fix_rounds: int = 2
    max_missing_polls: int = 10
    review_model: str = "same"
    review_model_slug: str | None = None
    worker_mix: str = "cursor-only"
    alternate_slug: str = "claude-sonnet-5-5-high"
    fallback: str | None = None
    orchestrator_id: str | None = None
    issues: dict[str, IssueRecord] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    escalation_enabled: bool = True
    escalation_premium_slug: str = "grok-4.7-high"
    escalation_max_per_batch: int = 2
    escalation_max_per_issue: int = 1
    composer_attempts_before_escalation: int = 1
    implementation_model_slug: str = "composer-2.5"
    effective_config: dict = field(default_factory=dict)
    events_tail_truncated: bool = False
    resource_lock_telemetry: str = "unavailable"
    escalation_batch_count: int = 0
    escalation_records: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> BatchState:
        version = data.get("version")
        if version != STATE_VERSION:
            raise PipelineError(
                f"unsupported state version: {version}",
                "state",
            )
        issues = {
            key: IssueRecord.from_dict(value)
            for key, value in (data.get("issues") or {}).items()
        }
        known = set(cls.__dataclass_fields__) - {"issues"}
        kwargs = {key: value for key, value in data.items() if key in known}
        kwargs["issues"] = issues
        return cls(**kwargs)

    def event(self, issue: str | None, name: str, detail: str = "") -> None:
        self.events.append(
            {
                "at": utc_now(),
                "issue": issue,
                "event": name,
                "detail": detail,
            }
        )
        if len(self.events) > 5000:
            self.events = self.events[-5000:]
            self.events_tail_truncated = True
        self.updated_at = utc_now()


def transition(issue: IssueRecord, new_state: str) -> None:
    allowed = ALLOWED.get(issue.state)
    if allowed is None or new_state not in allowed:
        raise TransitionError(
            f"{issue.key}: cannot move {issue.state} -> {new_state}"
        )
    issue.state = new_state


def occupies_slot(issue: IssueRecord, concurrency: int) -> bool:
    """Return whether this issue consumes a pipeline slot.

    Parallel mode counts implementation and review only. Sequential mode
    (concurrency <= 1) also waits out publish and CI before the next issue.
    """

    if issue.external or issue.state in {QUEUED, MERGED, BLOCKED}:
        return False
    if concurrency <= 1:
        return issue.state in SEQUENTIAL_BUSY
    return issue.state in AI_ACTIVE

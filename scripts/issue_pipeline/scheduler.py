"""Slot accounting, handoffs, and resume. This module does not call GitHub."""

from __future__ import annotations

import os
import re

from .dependencies import cascade_blocked
from .escalation import (
    VERIFIED_TASK_SLUGS,
    EscalationPolicy,
    apply_escalation,
    classify_new_vs_recurring,
    evaluate_premium_escalation,
    record_premium_outcome,
)
from .failure_categories import (
    CODE_DEFECT,
    HANDOFF_MALFORMED,
    INTEGRATION_CONFLICT,
    classify_ci_failure,
    classify_review_malformed,
    record_failure,
)
from .findings import validate_actionable_findings
from .handoff_validation import pytest_result_passed
from .handoffs import parse_handoff
from .telemetry import (
    ci_complete,
    ci_pending,
    deps_satisfied_record,
    mark_queued_schedule,
    note_capacity_waiters,
    phase_transition,
    record_worker_model,
    requested_model_for_action,
    worker_release,
    worker_start,
)
from .locks import assert_locked_verification
from .locks import pid_alive as default_pid_alive
from .models import (
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
    PipelineError,
    PublishError,
    TransitionError,
    occupies_slot,
    transition,
)

_TASKS = re.compile(r"(\d+)/(\d+)")
RETRYABLE_CI = {
    "check-not-success",
    "required-checks-unknown",
    "merge-unstable",
    "merge-blocked",
}


def deps_satisfied(issue: IssueRecord, state: BatchState) -> bool:
    for dep in issue.hard_dependencies:
        other = state.issues.get(dep)
        if other is None or other.state != MERGED:
            return False
    return True


def slots_used(state: BatchState) -> int:
    return sum(
        1
        for issue in state.issues.values()
        if occupies_slot(issue, state.concurrency)
    )


def next_actions(state: BatchState) -> dict:
    ongoing: list[dict] = []
    fresh: list[dict] = []
    ordered = sorted(state.issues.values(), key=lambda item: (item.queue_index, item.key))
    for issue in ordered:
        if issue.external:
            continue
        if issue.claimed:
            continue
        action = _action_for(issue, state)
        if action is None:
            continue
        payload = _action_payload(issue, action)
        if issue.state == QUEUED:
            fresh.append(payload)
        else:
            ongoing.append(payload)

    free = max(0, state.concurrency - slots_used(state))
    chosen = ongoing + fresh[:free]
    for payload in chosen:
        issue = state.issues[payload["issue"]]
        if payload["action"] == "review":
            payload["review_model_slug"] = state.review_model_slug
        payload["requested_model"] = requested_model_for_action(state, issue, payload["action"])
        payload["model_verified"] = (
            "verified"
            if payload["requested_model"]
            and payload["requested_model"] in VERIFIED_TASK_SLUGS
            else "requested-unverified"
        )
    publish = [
        _action_payload(issue, "submit")
        for issue in ordered
        if issue.state == READY and not issue.external
    ]
    revalidate = [
        _action_payload(issue, "revalidate")
        for issue in ordered
        if issue.state == PENDING_CI and issue.reason_code == "needs-revalidation"
    ]
    return {
        "concurrency": state.concurrency,
        "fallback": state.fallback,
        "slots_used": slots_used(state),
        "slots_free": free,
        "actions": chosen,
        "publish": publish,
        "revalidate": revalidate,
        "pending_ci": [
            issue.key for issue in ordered if issue.state == PENDING_CI
        ],
        "blocked": [
            {"issue": issue.key, "reason": issue.blocker, "code": issue.reason_code}
            for issue in ordered
            if issue.state == BLOCKED
        ],
    }


def dry_run(state: BatchState) -> dict:
    """Describe the batch the scheduler would run. Does not write state or git."""

    actions = next_actions(state)
    eligible = [item["issue"] for item in actions["actions"]]
    issues = []
    for issue in sorted(state.issues.values(), key=lambda item: (item.queue_index, item.key)):
        issues.append(
            {
                "issue": issue.key,
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "hard_dependencies": list(issue.hard_dependencies),
                "soft_conflicts": list(issue.soft_conflicts),
                "blocker": issue.blocker,
                "reason_code": issue.reason_code,
                "external": issue.external,
                "eligible": issue.key in eligible,
            }
        )
    return {
        "concurrency": state.concurrency,
        "fallback": state.fallback,
        "max_fix_rounds": state.max_fix_rounds,
        "full_suite_slots": 1,
        "merge_slots": 1,
        "initial_eligible": eligible,
        "simultaneous": eligible,
        "blocked": actions["blocked"],
        "issues": issues,
    }


def claim(
    state: BatchState,
    key: str,
    action: str,
    pid: int | None = None,
    *,
    worker_id: str | None = None,
    orchestrator_id: str | None = None,
) -> IssueRecord:
    issue = _require(state, key)
    owner = (worker_id or "").strip()
    if not owner and pid is not None:
        owner = f"pid-{pid}"
    if not owner:
        raise TransitionError("worker id is required")
    _bind_orchestrator(state, orchestrator_id)
    if issue.claimed:
        raise TransitionError(f"{key} is already claimed by {issue.worker_id or 'unknown'}")
    if action == "implement":
        _claim_implement(state, issue)
    elif action == "review":
        _claim_review(state, issue)
    else:
        raise TransitionError(f"unsupported claim action: {action}")
    issue.worker_id = owner
    issue.worker_pid = pid if pid and pid > 0 else None
    issue.claimed = True
    issue.interrupted = False
    state.event(key, "claim", f"{action} worker={owner}")
    requested = requested_model_for_action(state, issue, action)
    worker_start(state, issue, action=action, worker_id=owner, requested_model=requested)
    return issue


def attach_worker(
    state: BatchState,
    key: str,
    *,
    expect: str,
    worker_id: str,
    pid: int | None = None,
) -> IssueRecord:
    """Record a session id for a claim this orchestrator already owns."""

    issue = _require(state, key)
    owner = worker_id.strip()
    if not issue.claimed or issue.worker_id != expect or not owner:
        raise TransitionError(f"{key} claim does not match {expect}")
    issue.worker_id = owner
    if pid and pid > 0:
        issue.worker_pid = pid
    state.event(key, "attach", owner)
    return issue


def apply_implement_handoff(
    state: BatchState,
    key: str,
    fields: dict[str, str],
    *,
    head_sha: str,
    clean: bool,
) -> IssueRecord:
    issue = _require(state, key)
    if issue.state != IMPLEMENTING:
        raise TransitionError(f"{key} is {issue.state}, expected implementing")
    status = fields.get("Status", "")
    assert_locked_verification(fields.get("Verification", ""), fields.get("Pytest", ""))
    _clear_claim(issue)
    if status == "blocked" or fields.get("Tasks") == "partial":
        if status != "blocked":
            raise PipelineError("partial tasks require Status: blocked", "handoff")
        transition(issue, BLOCKED)
        issue.blocker = fields.get("Blocker") or "implementation blocked"
        issue.reason_code = "implement-blocked"
        issue.handoff_status = None
        cascade_blocked(state)
        state.event(key, "implement-blocked", issue.blocker or "")
        return issue
    if status != "ready-for-review":
        raise PipelineError(f"unexpected implement status: {status}", "handoff")
    if not clean:
        raise PipelineError("worktree is not clean", "handoff")
    if fields.get("SHA") != head_sha:
        raise PipelineError("handoff SHA does not match worktree HEAD", "handoff")
    if not issue.base_sha or fields.get("Base-SHA") != issue.base_sha:
        raise PipelineError("Base-SHA does not match the worktree base", "handoff")
    verification = fields.get("Verification") or ""
    if not verification.strip():
        raise PipelineError("verification is required", "handoff")
    issue.head_sha = head_sha
    issue.handoff_status = "ready-for-review"
    issue.verification = verification
    issue.notes = fields.get("Assumptions")
    issue.interrupted = False
    state.event(key, "ready-for-review", head_sha)
    worker_release(state, issue, detail=f"implement complete {head_sha}")
    phase_transition(state, issue, "ready-for-review", head_sha)
    note_capacity_waiters(state)
    return issue


def apply_review_handoff(
    state: BatchState,
    key: str,
    fields: dict[str, str],
    *,
    head_sha: str,
) -> IssueRecord:
    issue = _require(state, key)
    if issue.state != REVIEWING:
        raise TransitionError(f"{key} is {issue.state}, expected reviewing")
    assert_locked_verification(fields.get("Verification", ""), fields.get("Pytest", ""))
    _clear_claim(issue)
    verdict = fields.get("Verdict", "")
    reviewed = fields.get("Reviewed-SHA", "")
    if reviewed != head_sha:
        worker_release(state, issue, detail="malformed-reviewed-sha")
        return _malformed(state, issue, "Reviewed-SHA does not match worktree HEAD")
    if verdict in {"FIX FIRST", "NOT CLOSE"}:
        findings_text = (fields.get("Findings") or "").strip()
        finding_error = validate_actionable_findings(findings_text, verdict=verdict)
        if finding_error:
            worker_release(state, issue, detail="malformed-findings")
            return _malformed(state, issue, finding_error)
        issue.findings = findings_text
        issue.review_verdict = verdict
        issue.reviewed_sha = None
        issue.handoff_status = None
        recurring, new = classify_new_vs_recurring(issue.last_review_findings or "", findings_text)
        issue.review_history.append(
            {
                "at": state.updated_at,
                "verdict": verdict,
                "findings": findings_text,
                "recurring": recurring,
                "new": new,
                "recurring_count": len(recurring),
                "new_count": len(new),
            }
        )
        policy = _escalation_policy(state)
        premium_decision = evaluate_premium_escalation(
            state,
            issue,
            verdict=verdict,
            findings=findings_text,
            policy=policy,
        )
        if issue.last_implement_premium:
            record_premium_outcome(state, issue, success=False, reviewer_verdict=verdict)
            transition(issue, BLOCKED)
            issue.reason_code = "premium-failed"
            issue.blocker = findings_text
            issue.last_implement_premium = False
            cascade_blocked(state)
            state.event(key, "premium-failed", issue.blocker or "")
            return issue
        if issue.fix_round >= state.max_fix_rounds:
            if premium_decision and premium_decision.get("escalate"):
                apply_escalation(state, issue, premium_decision)
            else:
                transition(issue, BLOCKED)
                issue.reason_code = "fix-limit"
                issue.blocker = issue.findings
                issue.blocked_idle_since = state.updated_at
                cascade_blocked(state)
                state.event(key, "fix-limit", issue.blocker or "")
                state.event(key, "blocked-idle-start", "")
                return issue
        elif premium_decision and premium_decision.get("escalate"):
            apply_escalation(state, issue, premium_decision)
        issue.last_review_findings = findings_text
        transition(issue, NEEDS_FIX)
        issue.correction_kind = "implement"
        issue.blocker = issue.findings
        issue.reason_code = "review-fix"
        state.event(key, "needs-fix", verdict)
        worker_release(state, issue, detail=f"{verdict}: correction required")
        phase_transition(state, issue, "needs-fix", verdict)
        note_capacity_waiters(state)
        return issue
    if verdict != "READY":
        return _malformed(state, issue, f"unexpected verdict {verdict or 'missing'}")
    if fields.get("Base-SHA") != issue.base_sha:
        return _malformed(state, issue, "Base-SHA does not match the implementation base")
    pytest_result = fields.get("Pytest", "")
    if not pytest_result_passed(pytest_result):
        return _malformed(state, issue, f"pytest result is not passed: {pytest_result or 'missing'}")
    tasks = fields.get("Tasks-checked", "")
    match = _TASKS.fullmatch(tasks)
    if not match or match.group(1) != match.group(2):
        return _malformed(state, issue, f"tasks are not fully checked: {tasks or 'missing'}")
    verification = fields.get("Verification") or ""
    if not verification.strip():
        return _malformed(state, issue, "verification is required")
    issue.reviewed_sha = reviewed
    issue.head_sha = head_sha
    issue.review_verdict = "READY"
    issue.findings = fields.get("Findings") or "none"
    issue.verification = verification
    issue.tasks_checked = tasks
    issue.handoff_status = None
    issue.review_malformed = 0
    issue.blocker = None
    issue.reason_code = None
    issue.interrupted = False
    if issue.premium_attempts > 0:
        record_premium_outcome(
            state,
            issue,
            success=True,
            reviewer_verdict="READY",
            extra_attempts=issue.fix_round,
        )
    issue.review_history.append(
        {
            "at": state.updated_at,
            "verdict": "READY",
            "findings": issue.findings,
            "recurring_count": 0,
            "new_count": 0,
        }
    )
    transition(issue, READY)
    state.event(key, "ready-to-publish", reviewed)
    worker_release(state, issue, detail=f"review READY {reviewed}")
    phase_transition(state, issue, "ready-to-publish", reviewed)
    note_capacity_waiters(state)
    return issue


def apply_ci_decision(state: BatchState, issue: IssueRecord, decision, *, local_sha: str | None) -> None:
    """Apply a non-merge decision. Merge itself is performed by the publisher."""

    if issue.state == MERGING and decision.action not in {"already-merged"}:
        transition(issue, PENDING_CI)
    if issue.state not in {PENDING_CI, MERGING}:
        raise TransitionError(f"{issue.key} is {issue.state}, expected pending-ci")

    action = decision.action
    if action == "already-merged":
        return
    if action in {"wait", "retry"}:
        issue.notes = decision.reason
        if "missing:" in decision.reason:
            issue.missing_polls += 1
        else:
            issue.missing_polls = 0
        state.event(issue.key, "ci-wait", decision.reason)
        return
    if action == "needs-fix":
        category = classify_ci_failure(
            decision.reason,
            failed_checks=decision.failed_checks,
            verification=issue.verification,
        )
        _to_needs_fix(
            state,
            issue,
            decision.reason,
            "implement",
            decision.failed_checks,
            failure_category=category,
        )
        return
    if action == "invalidate-head":
        _invalidate_head(state, issue, decision.reason, local_sha)
        return
    if action == "needs-rereview":
        if "conflicts with the base branch" in decision.reason:
            _integration_correct(state, issue, decision.reason)
        else:
            _integration_review(state, issue, decision.reason)
        state.event(issue.key, "needs-rereview", decision.reason)
        return
    if action == "needs-integration-review":
        _integration_review(state, issue, decision.reason)
        return
    if action == "needs-integration-correct":
        _integration_correct(state, issue, decision.reason)
        return
    if action == "needs-revalidation":
        issue.reason_code = "needs-revalidation"
        issue.notes = decision.reason
        issue.integration_result = None
        issue.upstream_invalidation_count += 1
        state.event(issue.key, "upstream-invalidation", "disjoint")
        state.event(issue.key, "needs-revalidation", decision.reason)
        return
    if action == "block":
        code = _block_code(decision.reason)
        transition(issue, BLOCKED)
        issue.blocker = decision.reason
        issue.reason_code = code
        _clear_claim(issue)
        cascade_blocked(state)
        state.event(issue.key, "blocked", decision.reason)
        return
    raise PublishError(f"cannot apply decision {action}")


def record_integration(
    state: BatchState,
    key: str,
    base_sha: str,
    result: str,
    *,
    head_sha: str,
    clean: bool,
) -> IssueRecord:
    issue = _require(state, key)
    if issue.state != PENDING_CI:
        raise TransitionError(f"{key} is {issue.state}, expected pending-ci")
    if not clean or not issue.reviewed_sha or head_sha != issue.reviewed_sha:
        raise PublishError(
            "integration result rejected because the worktree does not match the reviewed SHA"
        )
    if result == "fail":
        _to_needs_fix(
            state,
            issue,
            f"integration validation failed for base {base_sha}",
            "implement",
            (),
            failure_category=INTEGRATION_CONFLICT,
            integration_correction=True,
        )
        return issue
    if result != "pass":
        raise PublishError("integration result must be pass or fail")
    issue.integration_base_sha = base_sha
    issue.integration_result = "pass"
    issue.upstream_base_sha = base_sha
    issue.reason_code = None
    issue.notes = f"integration validated at {base_sha}"
    state.event(key, "integration-pass", base_sha)
    state.event(key, "integration-revalidated", base_sha)
    return issue


def authorize_rebase(state: BatchState, key: str, *, expected_remote_sha: str) -> IssueRecord:
    """Allow a single guarded force-with-lease push on the next submit."""

    issue = _require(state, key)
    if not issue.pushed_sha:
        raise PublishError(f"{key} has not been pushed yet")
    if expected_remote_sha != issue.pushed_sha:
        raise PublishError(
            f"expected remote SHA {expected_remote_sha} does not match recorded pushed_sha"
        )
    issue.rebase_authorized = True
    state.event(key, "rebase-authorized", expected_remote_sha)
    return issue


def retry_ci(state: BatchState, key: str) -> IssueRecord:
    issue = _require(state, key)
    if issue.state != BLOCKED or issue.reason_code not in RETRYABLE_CI:
        raise TransitionError(f"{key} cannot return to CI from {issue.reason_code}")
    transition(issue, PENDING_CI)
    issue.blocker = None
    issue.reason_code = None
    issue.missing_polls = 0
    state.event(key, "retry-ci", "")
    return issue


def block_issue(state: BatchState, key: str, reason: str, code: str = "operator") -> IssueRecord:
    issue = _require(state, key)
    if issue.state == MERGED:
        raise TransitionError(f"{key} is already merged")
    if issue.state != BLOCKED:
        transition(issue, BLOCKED)
    issue.blocker = reason
    issue.reason_code = code
    _clear_claim(issue)
    cascade_blocked(state)
    state.event(key, "blocked", reason)
    return issue


def _verified_merge_sha(merge_sha: str) -> str:
    value = (merge_sha or "").strip()
    if len(value) < 7 or not all(ch in "0123456789abcdefABCDEF" for ch in value):
        raise TransitionError("merge requires a non-empty verified GitHub merge SHA")
    return value.lower()


def complete_merge(state: BatchState, issue: IssueRecord, merge_sha: str, method: str) -> None:
    merge_sha = _verified_merge_sha(merge_sha)
    if issue.state == MERGED:
        if not issue.merge_sha:
            issue.merge_sha = merge_sha
            state.event(issue.key, "merge-sha-reconciled", merge_sha)
        return
    if issue.state == PENDING_CI:
        transition(issue, MERGING)
    if issue.state != MERGING:
        raise TransitionError(f"{issue.key} is {issue.state}, expected merging")
    transition(issue, MERGED)
    issue.merge_sha = merge_sha
    issue.merge_method = method
    _clear_claim(issue)
    issue.blocker = None
    issue.reason_code = None
    issue.interrupted = False
    state.event(issue.key, "merged", f"{method} {merge_sha}")
    phase_transition(state, issue, "merged", merge_sha)
    worker_release(state, issue, detail=f"merged {merge_sha}")
    ci_complete(state, issue, "merged")
    release_dependents(state, issue.key)


def release_dependents(state: BatchState, merged_key: str) -> None:
    for issue in state.issues.values():
        if issue.state != BLOCKED or issue.reason_code != "blocked-prerequisite":
            continue
        if deps_satisfied(issue, state):
            transition(issue, QUEUED)
            issue.blocker = None
            issue.reason_code = None
            state.event(issue.key, "unblocked", f"after {merged_key}")
            deps_satisfied_record(state, issue)
            mark_queued_schedule(state, issue)


def record_worker_attachment(
    state: BatchState,
    key: str,
    *,
    phase: str,
    task_id: str,
    requested_model: str | None = None,
    confirmed_model: str | None = None,
    model_verified: str = "unknown",
) -> IssueRecord:
    issue = _require(state, key)
    verified = model_verified.lower()
    if verified not in {"yes", "no", "unknown"}:
        raise TransitionError("model_verified must be yes, no, or unknown")
    if confirmed_model and verified == "yes":
        pass
    elif not confirmed_model:
        verified = "unknown" if verified == "yes" else verified
    record_worker_model(
        issue,
        phase=phase,
        task_id=task_id,
        requested_model=requested_model,
        confirmed_model=confirmed_model,
        verified=verified,
    )
    detail = f"phase={phase} task={task_id} verified={verified}"
    state.event(key, "worker-model", detail)
    return issue


def authorize_premium_rescue(
    state: BatchState,
    key: str,
    *,
    note: str = "",
) -> IssueRecord:
    """Operator-authorized premium rescue after fix-limit without replaying review."""

    issue = _require(state, key)
    if issue.claimed:
        raise TransitionError(f"{key} is claimed by {issue.worker_id or 'unknown'}")
    if issue.state == NEEDS_FIX and issue.premium_pending:
        return issue
    if issue.operator_rescue_at and issue.state == BLOCKED:
        raise TransitionError(f"{key} operator rescue was already authorized for this block")
    if issue.state != BLOCKED or issue.reason_code != "fix-limit":
        raise TransitionError(f"{key} is {issue.state}/{issue.reason_code}; expected blocked fix-limit")
    findings = (issue.findings or issue.blocker or "").strip()
    finding_error = validate_actionable_findings(findings, verdict="FIX FIRST")
    if finding_error:
        raise TransitionError(finding_error)
    policy = _escalation_policy(state)
    if not policy.enabled:
        raise TransitionError("escalation is disabled")
    if not policy.slug_verified:
        raise TransitionError(f"premium slug not verified: {policy.premium_slug}")
    if issue.escalation_disabled:
        raise TransitionError("per-issue escalation is disabled")
    if issue.premium_attempts >= policy.max_per_issue:
        raise TransitionError("per-issue premium budget exhausted")
    if state.escalation_batch_count >= policy.max_per_batch:
        raise TransitionError("batch premium budget exhausted")

    recurring, new = classify_new_vs_recurring(issue.last_review_findings or "", findings)
    decision = {
        "escalate": True,
        "trigger": "operator_rescue",
        "original_model": issue.model_slug or "composer-inherit",
        "escalated_model": policy.premium_slug,
        "slug_verified": policy.slug_verified,
        "recurring_findings": recurring,
        "new_findings": new,
        "fix_round": issue.fix_round,
    }
    apply_escalation(state, issue, decision)
    transition(issue, NEEDS_FIX)
    issue.findings = findings
    issue.blocker = findings
    issue.correction_kind = "implement"
    issue.reason_code = "premium-rescue"
    issue.operator_rescue_at = state.updated_at
    issue.blocked_idle_since = None
    state.event(key, "blocked-idle-end", note or "rescue-authorized")
    state.event(key, "rescue-authorized", f"{policy.premium_slug} {note}".strip())
    phase_transition(state, issue, "premium-rescue", policy.premium_slug)
    note_capacity_waiters(state)
    return issue


def reconcile(
    state: BatchState,
    *,
    pr_for=None,
    alive=default_pid_alive,
    abandon: list[str] | None = None,
    orchestrator_id: str | None = None,
    takeover: bool = False,
) -> list[str]:
    """Repair state after a crash. Does not launch workers, merge, or touch git.

    A claim with a live pid stays owned. A claim whose pid is gone is released.
    A claim with no pid has unknown liveness and stays owned until `abandon`
    names that issue. Repeating the same call does not release a claim twice.
    """

    notes: list[str] = []
    _bind_orchestrator(state, orchestrator_id, takeover=takeover)
    requested = {str(key) for key in (abandon or [])}
    for issue in list(state.issues.values()):
        if issue.external:
            continue
        if issue.claimed:
            notes.append(_reconcile_claim(state, issue, alive=alive, requested=requested))
        if issue.pr_number and issue.state in {MERGING, PENDING_CI} and pr_for is not None:
            pr = pr_for(issue)
            if pr is not None and pr.state == "MERGED":
                if pr.merge_sha:
                    complete_merge(state, issue, pr.merge_sha, issue.merge_method or "observed")
                    notes.append(f"{issue.key}: observed merged PR #{pr.number}")
                else:
                    if issue.state == MERGING:
                        transition(issue, PENDING_CI)
                    issue.notes = "PR merged on GitHub but merge SHA is unavailable"
                    state.event(issue.key, "merge-incomplete", f"PR #{issue.pr_number}")
                    notes.append(f"{issue.key}: merged PR #{pr.number} missing merge SHA")
            elif issue.state == MERGING:
                transition(issue, PENDING_CI)
                notes.append(f"{issue.key}: merge was interrupted; returned to pending-ci")
                state.event(issue.key, "merge-interrupted", "")
    mentioned = {note.split(":", 1)[0] for note in notes}
    for key in sorted(requested):
        if key in mentioned:
            continue
        if key not in state.issues:
            notes.append(f"{key}: not in this batch")
        else:
            notes.append(f"{key}: not claimed")
    return notes


def _claim_implement(state: BatchState, issue: IssueRecord) -> None:
    if issue.state == QUEUED:
        if not deps_satisfied(issue, state):
            raise TransitionError(f"{issue.key} is waiting on a prerequisite")
        if slots_used(state) >= state.concurrency:
            raise TransitionError("concurrency limit reached")
        transition(issue, IMPLEMENTING)
        issue.handoff_status = None
        return
    if issue.state == NEEDS_FIX and issue.correction_kind == "integration-correct":
        if (
            issue.integration_correction_round >= state.max_fix_rounds
            and not issue.premium_pending
        ):
            transition(issue, BLOCKED)
            issue.reason_code = "fix-limit"
            issue.blocker = issue.blocker or "integration correction budget exhausted"
            cascade_blocked(state)
            raise TransitionError(issue.blocker or "integration correction budget exhausted")
        issue.integration_correction_round += 1
        transition(issue, IMPLEMENTING)
        issue.handoff_status = None
        issue.correction_kind = None
        return
    if issue.state == NEEDS_FIX and issue.correction_kind != "review-only":
        if issue.fix_round >= state.max_fix_rounds and not issue.premium_pending:
            transition(issue, BLOCKED)
            issue.reason_code = "fix-limit"
            issue.blocker = issue.blocker or "fix round limit reached"
            cascade_blocked(state)
            raise TransitionError(issue.blocker or "fix round limit reached")
        if issue.premium_pending:
            issue.premium_pending = False
            issue.premium_attempts += 1
            issue.last_implement_premium = True
        else:
            issue.last_implement_premium = False
            issue.fix_round += 1
        transition(issue, IMPLEMENTING)
        issue.handoff_status = None
        issue.correction_kind = None
        return
    if issue.state == IMPLEMENTING and issue.handoff_status != "ready-for-review":
        return
    raise TransitionError(f"cannot claim implement for {issue.key} in {issue.state}")


def _claim_review(state: BatchState, issue: IssueRecord) -> None:
    if issue.state == IMPLEMENTING and issue.handoff_status == "ready-for-review":
        transition(issue, REVIEWING)
        return
    if issue.state == NEEDS_FIX and issue.correction_kind == "review-only":
        transition(issue, REVIEWING)
        issue.correction_kind = None
        return
    if issue.state == REVIEWING:
        return
    raise TransitionError(f"cannot claim review for {issue.key} in {issue.state}")


def _action_for(issue: IssueRecord, state: BatchState) -> str | None:
    if issue.state == QUEUED:
        return "implement" if deps_satisfied(issue, state) else None
    if issue.state == IMPLEMENTING:
        if issue.handoff_status == "ready-for-review":
            return "review"
        return "implement"
    if issue.state == REVIEWING:
        return "review"
    if issue.state == NEEDS_FIX:
        if (
            issue.correction_kind != "review-only"
            and issue.fix_round >= state.max_fix_rounds
        ):
            return None
        if issue.correction_kind in {"review-only", "integration-review"}:
            return "review"
        if issue.correction_kind == "integration-correct":
            return "implement"
        return "implement"
    return None


def _action_payload(issue: IssueRecord, action: str) -> dict:
    return {
        "issue": issue.key,
        "number": issue.number,
        "action": action,
        "work_id": issue.work_id,
        "branch": issue.branch,
        "worktree": issue.worktree,
        "base_sha": issue.base_sha,
        "head_sha": issue.head_sha,
        "reviewed_sha": issue.reviewed_sha,
        "model_slug": issue.model_slug,
        "review_model_slug": None,
        "soft_conflicts": list(issue.soft_conflicts),
        "hard_dependencies": list(issue.hard_dependencies),
        "findings": issue.findings,
        "blocker": issue.blocker,
        "correction_kind": issue.correction_kind,
        "mode": issue.mode,
        "audit_report": issue.audit_report,
        "upstream_base_sha": issue.upstream_base_sha,
        "title": issue.title,
        "fix_round": issue.fix_round,
    }


def _clear_claim(issue: IssueRecord) -> None:
    issue.worker_pid = None
    issue.worker_id = None
    issue.claimed = False


def _bind_orchestrator(
    state: BatchState,
    orchestrator_id: str | None,
    *,
    takeover: bool = False,
) -> None:
    if not orchestrator_id:
        return
    current = state.orchestrator_id
    if current and current != orchestrator_id and not takeover:
        raise TransitionError(f"batch is owned by {current}")
    if current != orchestrator_id:
        state.orchestrator_id = orchestrator_id
        if takeover:
            state.event(None, "takeover", orchestrator_id)


def _reconcile_claim(state: BatchState, issue: IssueRecord, *, alive, requested: set[str]) -> str:
    owner = issue.worker_id or "unknown"
    if issue.worker_pid and alive(issue.worker_pid):
        return f"{issue.key}: worker {owner} pid {issue.worker_pid} is alive; claim kept"
    if issue.worker_pid:
        _release_claim(state, issue, "worker process is gone")
        return f"{issue.key}: worker process is gone; current phase can be relaunched"
    if issue.key in requested:
        _release_claim(state, issue, "operator abandoned an unknown worker")
        return f"{issue.key}: abandoned; worktree and branch were left in place"
    return f"{issue.key}: claim {owner} held; liveness unknown; not relaunching"


def _release_claim(state: BatchState, issue: IssueRecord, detail: str) -> None:
    _clear_claim(issue)
    issue.interrupted = True
    state.event(issue.key, "interrupted", detail)


def _escalation_policy(state: BatchState) -> EscalationPolicy:
    return EscalationPolicy(
        enabled=state.escalation_enabled,
        premium_slug=state.escalation_premium_slug,
        max_per_batch=state.escalation_max_per_batch,
        max_per_issue=state.escalation_max_per_issue,
        slug_verified=state.escalation_premium_slug in VERIFIED_TASK_SLUGS,
    )


def _malformed(state: BatchState, issue: IssueRecord, reason: str) -> IssueRecord:
    category = classify_review_malformed(reason)
    record_failure(
        issue,
        category=category,
        evidence=reason,
        action="review-retry" if issue.review_malformed == 0 else "blocked",
        at=state.updated_at,
    )
    issue.review_malformed += 1
    issue.interrupted = True
    issue.notes = reason
    if issue.review_malformed > 1:
        transition(issue, BLOCKED)
        issue.reason_code = "review-malformed"
        issue.blocker = reason
        cascade_blocked(state)
        state.event(issue.key, "review-malformed", reason)
    else:
        state.event(issue.key, "review-retry", reason)
    return issue


def _integration_review(state: BatchState, issue: IssueRecord, reason: str) -> None:
    issue.upstream_invalidation_count += 1
    issue.integration_result = None
    record_failure(
        issue,
        category=CODE_DEFECT,
        evidence=reason,
        action="integration-review",
        at=state.updated_at,
    )
    _to_needs_fix(
        state,
        issue,
        reason,
        "review-only",
        (),
        failure_category=CODE_DEFECT,
        preserve_reviewed_sha=True,
        counts_as_fix_round=False,
        reason_code="upstream-overlap",
    )
    state.event(issue.key, "upstream-invalidation", "overlap")
    state.event(issue.key, "needs-integration-review", reason)


def _integration_correct(state: BatchState, issue: IssueRecord, reason: str) -> None:
    issue.upstream_invalidation_count += 1
    issue.integration_result = None
    record_failure(
        issue,
        category=INTEGRATION_CONFLICT,
        evidence=reason,
        action="integration-correct",
        at=state.updated_at,
    )
    _to_needs_fix(
        state,
        issue,
        reason,
        "integration-correct",
        (),
        failure_category=INTEGRATION_CONFLICT,
        integration_correction=True,
        reason_code="integration-conflict",
    )
    state.event(issue.key, "upstream-invalidation", "conflict")
    state.event(issue.key, "needs-integration-correct", reason)


def _to_needs_fix(
    state,
    issue,
    reason: str,
    kind: str,
    failures,
    *,
    failure_category: str | None = None,
    preserve_reviewed_sha: bool = False,
    counts_as_fix_round: bool = True,
    integration_correction: bool = False,
    reason_code: str | None = None,
) -> None:
    category = failure_category or (
        CODE_DEFECT if kind in {"implement", "integration-correct"} else HANDOFF_MALFORMED
    )
    record_failure(
        issue,
        category=category,
        evidence=reason,
        action=f"needs-fix:{kind}",
        at=state.updated_at,
    )
    budget_kind = "implement" if kind == "implement" else kind
    if (
        budget_kind == "implement"
        and counts_as_fix_round
        and issue.fix_round >= state.max_fix_rounds
    ):
        if issue.state != BLOCKED:
            transition(issue, BLOCKED)
        issue.blocker = reason
        issue.reason_code = "fix-limit"
        issue.blocked_idle_since = state.updated_at
        _clear_claim(issue)
        cascade_blocked(state)
        state.event(issue.key, "fix-limit", reason)
        state.event(issue.key, "blocked-idle-start", "")
        return
    if (
        integration_correction
        and issue.integration_correction_round >= state.max_fix_rounds
    ):
        if issue.state != BLOCKED:
            transition(issue, BLOCKED)
        issue.blocker = reason
        issue.reason_code = "fix-limit"
        issue.blocked_idle_since = state.updated_at
        _clear_claim(issue)
        cascade_blocked(state)
        state.event(issue.key, "fix-limit", reason)
        state.event(issue.key, "blocked-idle-start", "")
        return
    issue.findings = reason
    if not preserve_reviewed_sha:
        issue.reviewed_sha = None
    issue.review_verdict = None
    issue.handoff_status = None
    issue.correction_kind = kind
    issue.blocker = reason
    if reason_code:
        issue.reason_code = reason_code
    elif kind == "implement":
        issue.reason_code = "ci-failed"
    elif kind == "integration-correct":
        issue.reason_code = "integration-conflict"
    else:
        issue.reason_code = "unreviewed-head"
    _clear_claim(issue)
    issue.ci_failures = [
        {"name": check.name, "url": check.url, "conclusion": check.conclusion}
        for check in failures
    ]
    if issue.state != NEEDS_FIX:
        transition(issue, NEEDS_FIX)
    state.event(issue.key, "needs-fix", reason)


def _invalidate_head(state, issue, reason: str, local_sha: str | None) -> None:
    remote = _sha_from_reason(reason, "remote head")
    if local_sha and remote and local_sha == remote:
        _to_needs_fix(state, issue, reason, "review-only", ())
        issue.head_sha = local_sha
        issue.reason_code = "unreviewed-head"
        return
    transition(issue, BLOCKED)
    issue.reason_code = "head-diverged"
    issue.blocker = reason if not local_sha else f"{reason}; local {local_sha}"
    _clear_claim(issue)
    cascade_blocked(state)
    state.event(issue.key, "head-diverged", issue.blocker or reason)


def _sha_from_reason(reason: str, label: str) -> str | None:
    marker = f"{label} "
    if marker not in reason:
        return None
    token = reason.split(marker, 1)[1].split(" ", 1)[0]
    return token or None


def _block_code(reason: str) -> str:
    lowered = reason.lower()
    if "could not be established" in lowered:
        return "required-checks-unknown"
    if "not successful" in lowered:
        return "check-not-success"
    if "unstable" in lowered:
        return "merge-unstable"
    if "changes" in lowered:
        return "changes-requested"
    return "merge-blocked"


def _require(state: BatchState, key: str) -> IssueRecord:
    try:
        return state.issues[str(key)]
    except KeyError as exc:
        raise PipelineError(f"unknown issue {key}", "state") from exc


def plan_audit(work_id: str, audit_report: str, title: str, *, concurrency: int = 1) -> BatchState:
    state = BatchState(concurrency=concurrency, fallback=None)
    state.issues[work_id] = IssueRecord(
        key=work_id,
        work_id=work_id,
        title=title or work_id,
        summary=title or work_id,
        mode="audit-fix",
        audit_report=audit_report,
        queue_index=0,
    )
    state.event(work_id, "prepared", "audit-fix")
    return state


def default_pid() -> int:
    return os.getpid()

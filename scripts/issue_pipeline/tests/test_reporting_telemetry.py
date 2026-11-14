from scripts.issue_pipeline.models import IMPLEMENTING, BatchState, IssueRecord
from scripts.issue_pipeline.reporting import build_batch_report
from scripts.issue_pipeline.telemetry import worker_release, worker_start

from .support import plan


def test_peak_concurrency_from_worker_events():
    state = plan("1\n2\n", [])
    state.issues["1"] = IssueRecord(key="1", number=1, state=IMPLEMENTING)
    state.issues["2"] = IssueRecord(key="2", number=2, state=IMPLEMENTING)
    worker_start(state, state.issues["1"], "implement", "w1")
    worker_start(state, state.issues["2"], "implement", "w2")
    worker_release(state, state.issues["1"], "ready")
    report = build_batch_report(state)
    scheduling = report["scheduling"]
    assert scheduling["peak_concurrency"] == 2
    assert not (report.get("telemetry") or {}).get("legacy_scheduling")


def test_truncation_warning_in_report():
    state = BatchState()
    state.events_tail_truncated = True
    state.issues["1"] = IssueRecord(key="1", number=1)
    report = build_batch_report(state)
    warnings = (report.get("telemetry") or {}).get("warnings") or []
    assert any("truncated" in w.lower() for w in warnings)
    assert report.get("events_truncated") is True


def test_legacy_scheduling_flag_without_worker_events():
    state = plan("1\n", [])
    state.event("1", "claim", "worker-a")
    report = build_batch_report(state)
    telemetry = report.get("telemetry") or {}
    assert telemetry.get("legacy_scheduling") is True
    scheduling = report.get("scheduling")
    assert scheduling is not None
    assert any(row.get("source") == "estimated-legacy" for row in scheduling.get("queue_waits") or [])

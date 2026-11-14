import json
from pathlib import Path

from scripts.issue_pipeline.cli import main
from scripts.issue_pipeline.models import BatchState, IssueRecord, MERGED, QUEUED
from scripts.issue_pipeline.reporting import build_batch_report, render_markdown_report
from scripts.issue_pipeline.scheduler import claim


def _sample_state() -> BatchState:
    state = BatchState(concurrency=3, created_at="2026-11-08T20:47:18+00:00")
    state.issues["1"] = IssueRecord(key="1", number=1, title="Alpha", queue_index=0, state=QUEUED)
    state.issues["2"] = IssueRecord(
        key="2",
        number=2,
        title="Beta",
        queue_index=1,
        hard_dependencies=["1"],
        state=QUEUED,
    )
    state.event(None, "prepared", "concurrency=3")
    claim(state, "1", "implement", worker_id="1-implement-1")
    state.event("1", "ready-for-review", "sha1")
    claim(state, "2", "implement", worker_id="2-implement-1")
    claim(state, "1", "review", worker_id="1-review-1")
    state.event("1", "ready-to-publish", "sha1")
    state.issues["1"].state = MERGED
    return state


def test_dependency_waves_and_peak_concurrency():
    report = build_batch_report(_sample_state())
    assert report["scheduling"]["waves"][0] == ["1"]
    assert report["scheduling"]["waves"][1] == ["2"]
    assert report["scheduling"]["peak_concurrency"] >= 2
    assert "gantt" in report["diagrams"]["mermaid_gantt"]


def test_missing_timestamps_still_emit_report():
    state = BatchState()
    state.issues["1"] = IssueRecord(key="1", number=1, title="Solo")
    report = build_batch_report(state)
    assert report["issues"][0]["durations"]["total"] is not None
    md = render_markdown_report(report)
    assert "Issue pipeline batch report" in md


def test_report_cli_writes_files(tmp_path: Path, capsys):
    state_path = tmp_path / "state.json"
    state = _sample_state()
    state_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    md = tmp_path / "out.md"
    js = tmp_path / "out.json"
    code = main(["--state", str(state_path), "report", "--markdown", str(md), "--json", str(js)])
    assert code == 0
    assert md.read_text(encoding="utf-8").startswith("# Issue pipeline batch report")
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["metrics"]["total_issues"] == 2
    assert "markdown" in json.loads(capsys.readouterr().out) is False


def test_load_handoffs_collects_md_and_txt(tmp_path: Path):
    handoffs = tmp_path / "handoffs"
    handoffs.mkdir()
    (handoffs / "689-implement-1.md").write_text("WORKER_HANDOFF\n", encoding="utf-8")
    (handoffs / "689-review-1.md").write_text("REVIEW_HANDOFF\n", encoding="utf-8")
    (handoffs / "690-implement-1.txt").write_text("legacy\n", encoding="utf-8")
    state = BatchState()
    state.issues["689"] = IssueRecord(key="689", number=689, title="A")
    state.issues["690"] = IssueRecord(key="690", number=690, title="B")
    report = build_batch_report(state, handoffs_dir=handoffs)
    assert len(report["handoffs"]["689"]) == 2
    assert any(p.endswith("689-implement-1.md") for p in report["handoffs"]["689"])
    assert len(report["handoffs"]["690"]) == 1


def test_real_state_snapshot_report(repo_root: Path | None = None):
    path = Path(__file__).resolve().parents[3] / ".chatvector" / "issue-pipeline" / "state.json"
    if not path.is_file():
        return
    state = BatchState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    report = build_batch_report(state)
    assert report["metrics"]["total_issues"] == 3
    assert report["scheduling"]["peak_concurrency"] >= 2
    assert "629" in report["diagrams"]["ascii_timeline"]

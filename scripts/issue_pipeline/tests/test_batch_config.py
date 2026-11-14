import json
from pathlib import Path

import pytest

from scripts.issue_pipeline.batch_config import (
    resolve_batch_config,
    validate_worker_slug,
)
from scripts.issue_pipeline.models import GraphError
from scripts.issue_pipeline.queue import parse_queue, parse_issue_line

from .support import plan, snapshot


def test_repository_defaults_apply_with_config_file(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "issue-pipeline.json").write_text(
        json.dumps(
            {
                "batch": {
                    "concurrency": 3,
                    "implementation_model": "composer-2.5",
                    "review_model": "composer-2.5",
                },
                "escalation": {
                    "enabled": True,
                    "premium_slug": "grok-4.7-high",
                    "max_per_batch": 2,
                    "composer_attempts_before_escalation": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    resolved = resolve_batch_config(repo_root=tmp_path)
    assert resolved.concurrency == 3
    assert resolved.escalation_enabled is True
    assert resolved.escalation_premium_slug == "grok-4.7-high"
    assert resolved.composer_attempts_before_escalation == 1


def test_batch_queue_overrides_repository_defaults(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "issue-pipeline.json").write_text(
        json.dumps({"escalation": {"enabled": True, "max_per_batch": 2}}),
        encoding="utf-8",
    )
    resolved = resolve_batch_config(
        repo_root=tmp_path,
        queue_concurrency=2,
        queue_escalation_enabled=False,
        queue_escalation_max_batch=0,
    )
    assert resolved.concurrency == 2
    assert resolved.escalation_enabled is False


def test_fast_variant_is_rejected():
    with pytest.raises(GraphError) as exc:
        validate_worker_slug("cursor-grok-4.6-high-fast", label="Issue model")
    assert "Fast variant" in str(exc.value)


def test_per_issue_model_and_escalation_annotations():
    item = parse_issue_line("701 (model: grok-4.7)")
    assert item.issue_model == "grok-4.7"
    dep_item = parse_issue_line("702 (after 701)")
    assert dep_item.hard_dependencies == [701]
    esc_off = parse_issue_line("703 (escalation: disabled)")
    assert esc_off.escalation_disabled is True


def test_per_issue_model_precedence_in_build(tmp_path: Path):
    state = plan(
        "701 (model: grok-4.7-high)\n702 (after 701) (escalation: disabled)\n",
        [snapshot(701), snapshot(702, body="Depends on #701")],
        repo_root=tmp_path,
    )
    assert state.issues["701"].model_slug == "grok-4.7-high"
    assert state.issues["702"].escalation_disabled is True


def test_invalid_escalation_budget_raises():
    with pytest.raises(GraphError) as exc:
        resolve_batch_config(
            repo_root=None,
            queue_escalation_enabled=True,
            queue_escalation_max_batch=0,
        )
    assert "contradictory" in str(exc.value).lower()


def test_dependency_parsing_with_model_override():
    state = plan(
        "701 (model: grok-4.7)\n702 (after 701)\n",
        [snapshot(701), snapshot(702)],
    )
    assert "701" in state.issues["702"].hard_dependencies


def test_plan_prints_effective_config(tmp_path: Path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "issue-pipeline.json").write_text(
        json.dumps({"escalation": {"enabled": True}}),
        encoding="utf-8",
    )
    state = plan("701\n", [snapshot(701)], repo_root=tmp_path)
    assert state.effective_config.get("implementation_model") == "composer-2.5"
    assert state.escalation_enabled is True
    assert any(event.get("event") == "config-resolved" for event in state.events)

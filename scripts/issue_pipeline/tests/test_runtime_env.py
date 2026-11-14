import os
from pathlib import Path

from scripts.issue_pipeline.runtime_env import prepend_tool_path


def test_prepend_tool_path_adds_venv_bin(tmp_path: Path, monkeypatch):
    venv_bin = tmp_path / "backend" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "pytest").write_text("", encoding="utf-8")
    monkeypatch.delenv("PIPELINE_SKIP_PATH_BOOTSTRAP", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    prepend_tool_path(tmp_path)
    assert str(venv_bin) in os.environ["PATH"].split(":")[0]


def test_prepend_skipped_when_env_set(tmp_path: Path, monkeypatch):
    venv_bin = tmp_path / "backend" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    monkeypatch.setenv("PIPELINE_SKIP_PATH_BOOTSTRAP", "1")
    monkeypatch.setenv("PATH", "/usr/bin")
    prepend_tool_path(tmp_path)
    assert os.environ["PATH"] == "/usr/bin"
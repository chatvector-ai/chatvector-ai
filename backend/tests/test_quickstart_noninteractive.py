"""Regression tests for non-interactive make quickstart provider setup."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV = REPO_ROOT / "backend" / ".env"
BACKEND_ENV_EXAMPLE = REPO_ROOT / "backend" / ".env.example"


def _write_stub_bin(directory: Path) -> Path:
    bindir = directory / "stubs"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
if [[ "${1:-}" == "info" ]]; then exit 0; fi
if [[ "${1:-}" == "compose" ]]; then exit 0; fi
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    for name in ("curl", "node", "npm"):
        script = bindir / name
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
    return bindir


def _run_bash(repo_root: Path, script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", script],
        cwd=repo_root,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture
def incomplete_backend_env():
    """Use placeholder Gemini credentials so provider setup is incomplete."""
    backup: str | None = None
    if BACKEND_ENV.exists():
        backup = BACKEND_ENV.read_text(encoding="utf-8")
    shutil.copy(BACKEND_ENV_EXAMPLE, BACKEND_ENV)
    try:
        yield BACKEND_ENV
    finally:
        if backup is None:
            BACKEND_ENV.unlink(missing_ok=True)
        else:
            BACKEND_ENV.write_text(backup, encoding="utf-8")


def test_handle_quickstart_non_tty_returns_nonzero(incomplete_backend_env, tmp_path):
    stub_bin = _write_stub_bin(tmp_path)
    result = _run_bash(
        REPO_ROOT,
        "source scripts/lib/common.sh && handle_quickstart_provider_configuration",
        env={"PATH": f"{stub_bin}:{os.environ.get('PATH', '')}"},
    )
    assert result.returncode == 1
    assert "make quickstart" in result.stdout
    assert "make setup" not in result.stdout


def test_quickstart_setup_non_tty_exits_before_dev(
    incomplete_backend_env, tmp_path
):
    stub_bin = _write_stub_bin(tmp_path)
    env = {
        "PATH": f"{stub_bin}:{os.environ.get('PATH', '')}",
        "QUICKSTART": "1",
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", str(REPO_ROOT / "scripts/setup.sh")],
        cwd=REPO_ROOT,
        env={**os.environ, **env},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Starting backend Docker stack" not in result.stdout + result.stderr
    assert result.stdout.count("Backend provider configuration is incomplete") == 1


def test_make_quickstart_non_tty_stops_before_dev(incomplete_backend_env, tmp_path):
    stub_bin = _write_stub_bin(tmp_path)
    result = subprocess.run(
        ["make", "quickstart"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{stub_bin}:{os.environ.get('PATH', '')}",
        },
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Starting backend Docker stack" not in combined
    assert "Development environment running" not in combined
    assert combined.count("Backend provider configuration is incomplete") == 1
    assert "Complete backend/.env, then run: make" not in combined


def test_handle_quickstart_succeeds_when_configuration_complete(tmp_path):
    stub_bin = _write_stub_bin(tmp_path)
    work_root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "scripts", work_root / "scripts")
    backend = work_root / "backend"
    backend.mkdir()
    env_file = backend / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_PROVIDER=gemini",
                "EMBEDDING_PROVIDER=gemini",
                "GEN_AI_KEY=integration-test-gemini-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = _run_bash(
        work_root,
        "source scripts/lib/common.sh && handle_quickstart_provider_configuration",
        env={"PATH": f"{stub_bin}:{os.environ.get('PATH', '')}"},
    )
    assert result.returncode == 0
    assert "Provider configuration already complete" in result.stdout

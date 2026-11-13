"""Regression tests for Ollama Docker connectivity preflight in scripts/lib/providers.sh."""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

from tests.repo_layout import repo_file

_REPO_ROOT = repo_file("scripts", "lib", "providers.sh").parents[2]
_PROVIDERS_SH = _REPO_ROOT / "scripts" / "lib" / "providers.sh"

_VERIFY_RUNNER = textwrap.dedent(
    """
    set -euo pipefail
    REPO_ROOT="{repo_root}"
    SCRIPT_DIR="${{REPO_ROOT}}/scripts/lib"
    BACKEND_ENV="${{TEST_ENV_FILE}}"
    # shellcheck source=/dev/null
    source "${{SCRIPT_DIR}}/env.sh"

    read_env_value() {{
      local file="$1"
      local key="$2"
      local line value

      line="$(grep -E "^${{key}}=" "${{file}}" 2>/dev/null | tail -n 1 || true)"
      if [[ -z "${{line}}" ]]; then
        return 0
      fi
      value="${{line#*=}}"
      value="${{value%\\"}}"
      value="${{value#\\"}}"
      value="${{value%\\'}}"
      value="${{value#\\'}}"
      printf '%s' "${{value}}"
    }}

    # shellcheck source=/dev/null
    source "${{SCRIPT_DIR}}/providers.sh"

    docker_compose() {{
      if [[ "${{STUB_CONTAINER_OK}}" == "1" ]]; then
        return 0
      fi
      return 1
    }}

    verify_ollama_docker_connectivity
    """
).format(repo_root=_REPO_ROOT)


def _run_verify(*, env_lines: list[str], stub_container_ok: bool = True) -> subprocess.CompletedProcess[str]:
    """Invoke verify_ollama_docker_connectivity with a temp backend/.env and stubbed docker."""
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as tmp:
        tmp.write("\n".join(env_lines) + "\n")
        env_path = tmp.name

    try:
        return subprocess.run(
            ["bash", "-c", _VERIFY_RUNNER],
            cwd=_REPO_ROOT,
            env={
                **os.environ,
                "TEST_ENV_FILE": env_path,
                "STUB_CONTAINER_OK": "1" if stub_container_ok else "0",
            },
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        Path(env_path).unlink(missing_ok=True)


@pytest.mark.parametrize(
    "env_lines,expect_ok,stderr_fragment",
    [
        (
            ["LLM_PROVIDER=ollama", "EMBEDDING_PROVIDER=ollama"],
            False,
            "http://host.docker.internal:11434",
        ),
        (
            [
                "LLM_PROVIDER=ollama",
                "EMBEDDING_PROVIDER=ollama",
                "OLLAMA_BASE_URL=http://localhost:11434",
            ],
            False,
            "http://host.docker.internal:11434",
        ),
        (
            [
                "LLM_PROVIDER=ollama",
                "EMBEDDING_PROVIDER=ollama",
                "OLLAMA_BASE_URL=http://host.docker.internal:11434",
            ],
            True,
            "",
        ),
        (
            ["LLM_PROVIDER=gemini", "EMBEDDING_PROVIDER=gemini"],
            True,
            "",
        ),
    ],
)
def test_verify_ollama_docker_connectivity(
    env_lines: list[str],
    expect_ok: bool,
    stderr_fragment: str,
) -> None:
    assert _PROVIDERS_SH.is_file()
    completed = _run_verify(env_lines=env_lines)
    if expect_ok:
        assert completed.returncode == 0, completed.stderr
    else:
        assert completed.returncode != 0
        assert stderr_fragment in completed.stderr

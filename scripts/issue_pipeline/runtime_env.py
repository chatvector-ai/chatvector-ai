"""Local tool PATH helpers for publisher subprocesses (pytest, psql)."""

from __future__ import annotations

import os
from pathlib import Path


def prepend_tool_path(repo_root: Path) -> None:
    """Prepend backend venv and Homebrew libpq so tick/revalidate find pytest and psql."""

    if os.environ.get("PIPELINE_SKIP_PATH_BOOTSTRAP") == "1":
        return
    prefixes: list[str] = []
    venv_bin = (repo_root / "backend" / ".venv" / "bin").resolve()
    if venv_bin.is_dir():
        prefixes.append(str(venv_bin))
    for libpq in (Path("/opt/homebrew/opt/libpq/bin"), Path("/usr/local/opt/libpq/bin")):
        if (libpq / "psql").is_file():
            prefixes.append(str(libpq))
            break
    if not prefixes:
        return
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = ":".join(prefixes) + (":" + current if current else "")
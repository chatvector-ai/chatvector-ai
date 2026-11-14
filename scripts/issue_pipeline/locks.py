"""File locks for the full test suite and for squash merges."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import fcntl

from .models import PipelineError


class LockTimeout(PipelineError):
    def __init__(self, message: str):
        super().__init__(message, "lock")


_DOCKER = re.compile(r"\bdocker(?:-|\s+)compose\b", re.IGNORECASE)
_MAKE_TESTS = re.compile(r"\bmake\s+tests\b", re.IGNORECASE)
_NPM_BUILD = re.compile(r"\bnpm\b.*\brun\s+build\b", re.IGNORECASE)
_PYTEST = re.compile(r"\bpytest\b([^|&;\n]*)", re.IGNORECASE)
_LOCK_USE = re.compile(r"issue-pipeline\s+(verify|lock\s+exec)")
_CLAIMED_SUITE = re.compile(r"\bpytest\s+passed\b|^(passed|failed)\b", re.IGNORECASE | re.MULTILINE)
_PROSE = {"passed", "failed", "not", "run", "with", "count", "none"}


def text_needs_lock(text: str) -> bool:
    """Full suites, Compose test stacks, and frontend builds share one lock."""

    if _DOCKER.search(text) or _MAKE_TESTS.search(text) or _NPM_BUILD.search(text):
        return True
    for match in _PYTEST.finditer(text):
        words = match.group(1).split()
        targets = [word for word in words if not word.startswith("-")]
        if not targets:
            return bool(words)
        if all(word.lower().strip(".,:") in _PROSE for word in targets):
            continue
        for target in targets:
            if _suite_target(target):
                return True
    return False


def _suite_target(token: str) -> bool:
    path = token.split("::", 1)[0].rstrip("/")
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        return False
    return name == "tests" or path in {"backend/tests", "tests"}


def command_needs_lock(command: list[str]) -> bool:
    return text_needs_lock(" ".join(command))


def assert_locked_verification(*parts: str) -> None:
    text = "\n".join(part for part in parts if part)
    suite_claimed = bool(_CLAIMED_SUITE.search(text))
    if (text_needs_lock(text) or suite_claimed) and not _LOCK_USE.search(text):
        raise PipelineError(
            "full pytest, Docker Compose tests, and frontend builds must run "
            "under scripts/issue-pipeline verify",
            "handoff",
        )


def pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class FileLock:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def acquire(self, *, wait: bool = False, timeout: float = 0):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lockfile = self.path.with_suffix(self.path.suffix + ".flock")
        deadline = time.monotonic() + max(timeout, 0)
        with open(lockfile, "a+", encoding="utf-8") as handle:
            while True:
                try:
                    fcntl.flock(
                        handle.fileno(),
                        fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                except BlockingIOError:
                    if not wait or time.monotonic() >= deadline:
                        raise LockTimeout(f"could not acquire {self.path.name}") from None
                    time.sleep(0.05)
                    continue
                self.path.write_text(
                    json.dumps({"pid": os.getpid()}),
                    encoding="utf-8",
                )
                try:
                    yield
                finally:
                    if self.path.exists():
                        self.path.unlink()
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return


def run_locked(
    path: Path,
    command: list[str],
    *,
    wait: bool = True,
    timeout: float = 7200,
    cwd: Path | None = None,
) -> int:
    if not command:
        raise PipelineError("lock exec requires a command", "lock")
    with FileLock(path).acquire(wait=wait, timeout=timeout):
        completed = subprocess.run(command, cwd=cwd, check=False)
        return completed.returncode


def run_verified(
    path: Path,
    command: list[str],
    *,
    cwd: Path | None = None,
    wait: bool = True,
    timeout: float = 7200,
) -> tuple[int, bool]:
    if command_needs_lock(command):
        return run_locked(path, command, wait=wait, timeout=timeout, cwd=cwd), True
    completed = subprocess.run(command, cwd=cwd, check=False)
    return completed.returncode, False


@contextmanager
def merge_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

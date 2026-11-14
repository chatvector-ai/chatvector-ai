"""JSON batch state with an exclusive file lock around each mutation."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

import fcntl

from .models import BatchState, PipelineError


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, state: BatchState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            self._write(state)

    def load(self) -> BatchState:
        with self._locked():
            return self._read()

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            state = self._read() if self.path.exists() else BatchState()
            try:
                yield state
            except Exception:
                raise
            else:
                self._write(state)

    @contextmanager
    def _locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self) -> BatchState:
        if not self.path.exists():
            raise PipelineError(f"no pipeline state at {self.path}", "state")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PipelineError(f"corrupt pipeline state: {exc}", "state") from exc
        return BatchState.from_dict(data)

    def _write(self, state: BatchState) -> None:
        payload = json.dumps(state.to_dict(), indent=2, sort_keys=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

import threading
from pathlib import Path

import pytest

from scripts.issue_pipeline.locks import FileLock, LockTimeout, merge_lock


def test_suite_lock_excludes_a_second_holder(tmp_path: Path):
    lock = FileLock(tmp_path / "full-suite.json")
    started = threading.Event()
    release = threading.Event()

    def hold():
        with lock.acquire(wait=True, timeout=2):
            started.set()
            assert release.wait(2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert started.wait(2)
    with pytest.raises(LockTimeout):
        with lock.acquire(wait=False):
            pass
    release.set()
    thread.join()
    with lock.acquire(wait=False):
        assert True


def test_merge_lock_serializes_callers(tmp_path: Path):
    path = tmp_path / "merge.lock"
    order = []
    started = threading.Barrier(2)

    def attempt(name):
        started.wait()
        with merge_lock(path):
            order.append(f"start-{name}")
            order.append(f"end-{name}")

    threads = [threading.Thread(target=attempt, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert order in (
        ["start-a", "end-a", "start-b", "end-b"],
        ["start-b", "end-b", "start-a", "end-a"],
    )

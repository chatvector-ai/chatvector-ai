"""Tests for logging_config.setup_logging() log-file routing.

Locks in the APP_ENV-based routing added in
https://github.com/chatvector-ai/chatvector-ai/pull/236:

- APP_ENV=test  -> logs/test.log + logs/test_access.log
- otherwise     -> logs/app.log  + logs/access.log

These tests would have caught the conftest.py default-to-production bug
that let test output leak into app.log on direct-pytest runs.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

import pytest


def _file_handler_paths(logger: logging.Logger) -> list[str]:
    """Return normalized basenames of every RotatingFileHandler on a logger."""
    return [
        os.path.basename(h.baseFilename).replace("\\", "/")
        for h in logger.handlers
        if isinstance(h, RotatingFileHandler)
    ]


@pytest.fixture
def reset_logging():
    """Snapshot + restore handler state around each test.

    setup_logging() mutates root + uvicorn loggers globally; without this
    fixture the side effects leak into other tests.
    """
    targets = [
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("uvicorn.access"),
    ]
    saved = [(lg, list(lg.handlers), lg.level, lg.propagate) for lg in targets]
    try:
        yield
    finally:
        for lg, handlers, level, propagate in saved:
            # Close any handlers setup_logging opened so file descriptors
            # don't leak between tests.
            for h in lg.handlers:
                if h not in handlers:
                    try:
                        h.close()
                    except Exception:
                        pass
            lg.handlers = handlers
            lg.setLevel(level)
            lg.propagate = propagate


def test_setup_logging_routes_to_test_files_when_app_env_is_test(
    monkeypatch, reset_logging
):
    """APP_ENV=test -> root logger writes to logs/test.log;
    uvicorn.access writes to logs/test_access.log."""
    from logging_config.logging_config import setup_logging

    monkeypatch.setenv("APP_ENV", "test")
    setup_logging()

    root_files = _file_handler_paths(logging.getLogger())
    access_files = _file_handler_paths(logging.getLogger("uvicorn.access"))

    assert "test.log" in root_files, (
        f"expected test.log on root logger, got {root_files}"
    )
    assert "test_access.log" in access_files, (
        f"expected test_access.log on uvicorn.access, got {access_files}"
    )
    # Negative assertion: production files must not be attached.
    assert "app.log" not in root_files
    assert "access.log" not in access_files


def test_setup_logging_routes_to_production_files_when_app_env_is_development(
    monkeypatch, reset_logging
):
    """APP_ENV=development (and any non-test value) -> logs/app.log +
    logs/access.log. Confirms test routing is opt-in, not default."""
    from logging_config.logging_config import setup_logging

    monkeypatch.setenv("APP_ENV", "development")
    setup_logging()

    root_files = _file_handler_paths(logging.getLogger())
    access_files = _file_handler_paths(logging.getLogger("uvicorn.access"))

    assert "app.log" in root_files, (
        f"expected app.log on root logger, got {root_files}"
    )
    assert "access.log" in access_files, (
        f"expected access.log on uvicorn.access, got {access_files}"
    )
    assert "test.log" not in root_files
    assert "test_access.log" not in access_files

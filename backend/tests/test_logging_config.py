"""Tests for logging_config.setup_logging() log-file routing."""
import json
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

    monkeypatch.delenv("CHATVECTOR_TEST_LOGGING", raising=False)
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


def test_setup_logging_routes_to_test_files_when_pytest_flag_set(
    monkeypatch, reset_logging
):
    """CHATVECTOR_TEST_LOGGING keeps reload tests on test.log."""
    from logging_config.logging_config import setup_logging

    monkeypatch.setenv("CHATVECTOR_TEST_LOGGING", "1")
    monkeypatch.setenv("APP_ENV", "development")
    setup_logging()

    root_files = _file_handler_paths(logging.getLogger())
    access_files = _file_handler_paths(logging.getLogger("uvicorn.access"))

    assert "test.log" in root_files
    assert "test_access.log" in access_files
    assert "app.log" not in root_files
    assert "access.log" not in access_files


def test_setup_logging_root_has_file_and_stream_handlers(monkeypatch, reset_logging):
    from logging_config.logging_config import setup_logging

    monkeypatch.setenv("APP_ENV", "development")
    setup_logging()

    root = logging.getLogger()
    handler_types = {type(h).__name__ for h in root.handlers}
    assert "RotatingFileHandler" in handler_types
    assert "StreamHandler" in handler_types


def test_setup_logging_application_record_reaches_console(monkeypatch, reset_logging):
    import io

    from logging_config.logging_config import setup_logging

    monkeypatch.setenv("APP_ENV", "development")
    setup_logging()

    root = logging.getLogger()
    stream_handler = next(
        h for h in root.handlers if type(h).__name__ == "StreamHandler"
    )
    buffer = io.StringIO()
    stream_handler.stream = buffer

    logging.getLogger("app.test.console").info("console-visible-message")
    assert "console-visible-message" in buffer.getvalue()


def test_setup_logging_uvicorn_does_not_propagate_to_root(monkeypatch, reset_logging):
    from logging_config.logging_config import setup_logging

    monkeypatch.setenv("APP_ENV", "development")
    setup_logging()

    uvicorn_logger = logging.getLogger("uvicorn.access")
    assert uvicorn_logger.propagate is False


def test_json_formatter_includes_extra_fields():
    from logging_config.logging_config import JSONFormatter

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="rate limited",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-1"
    record.event = "rate_limited"
    record.tenant_id = "abc"

    payload = json.loads(formatter.format(record))
    assert payload["event"] == "rate_limited"
    assert payload["tenant_id"] == "abc"
    assert payload["level"] == "INFO"


def test_json_formatter_extra_cannot_overwrite_canonical_fields():
    from logging_config.logging_config import JSONFormatter

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="real message",
        args=(),
        exc_info=None,
    )
    record.level = "HACK"
    record.message = "spoof"

    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["message"] == "real message"

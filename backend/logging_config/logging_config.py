import logging
import json
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime
from typing import Any

from logging_config.logging_filters import RequestIDFilter
from core.config import config


# Standard LogRecord attributes — never emit as structured extras.
_STANDARD_LOG_RECORD_ATTRS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
)
# Canonical JSON keys that extras must not overwrite.
_JSON_CANONICAL_KEYS = frozenset({
    "timestamp",
    "level",
    "logger",
    "message",
    "request_id",
    "exception",
})


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    Converts log records to JSON format for machine readability.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_ATTRS:
                continue
            if key in _JSON_CANONICAL_KEYS:
                continue
            log_data[key] = value

        return json.dumps(log_data)


def _uses_test_log_files() -> bool:
    """Return True when file handlers should write under logs/test*.log."""
    app_env = os.environ.get("APP_ENV", "production").lower()
    if app_env == "test":
        return True
    pytest_logging = os.environ.get("CHATVECTOR_TEST_LOGGING", "").strip().lower()
    return pytest_logging in {"1", "true", "yes", "on"}


def setup_logging(
    log_file: str | None = None,
    access_log_file: str | None = None,
) -> None:
    """
    Logging strategy:
    - Application logs -> logs/app.log AND stdout (with request_id)
    - Uvicorn access logs -> logs/access.log AND console
    - No duplicate logs through uvicorn propagation
    - Supports JSON format when LOG_FORMAT=JSON is set

    When APP_ENV=test or CHATVECTOR_TEST_LOGGING is set (pytest conftest), writes
    to logs/test.log and logs/test_access.log instead of the production log files
    so reload tests that temporarily use development/production APP_ENV do not
    pollute app.log.
    """
    route_test_logs = _uses_test_log_files()

    if log_file is None:
        log_file = "logs/test.log" if route_test_logs else "logs/app.log"
    if access_log_file is None:
        access_log_file = (
            "logs/test_access.log" if route_test_logs else "logs/access.log"
        )

    logging.captureWarnings(True)

    log_path = Path(log_file)
    access_log_path = Path(access_log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    access_log_path.parent.mkdir(parents=True, exist_ok=True)

    if config.LOG_FORMAT == "JSON":
        app_formatter = JSONFormatter()
        uvicorn_formatter = JSONFormatter()
    else:
        app_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - "
            "[request_id=%(request_id)s] - %(message)s"
        )
        uvicorn_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,
        backupCount=5,
    )
    file_handler.setFormatter(app_formatter)
    file_handler.addFilter(RequestIDFilter())

    app_console_handler = logging.StreamHandler()
    app_console_handler.setFormatter(app_formatter)
    app_console_handler.addFilter(RequestIDFilter())

    uvicorn_console_handler = logging.StreamHandler()
    uvicorn_console_handler.setFormatter(uvicorn_formatter)

    access_file_handler = RotatingFileHandler(
        access_log_file,
        maxBytes=10_000_000,
        backupCount=5,
    )
    access_file_handler.setFormatter(uvicorn_formatter)

    log_level = getattr(logging, config.LOG_LEVEL, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(app_console_handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(uvicorn_console_handler)
        logger.addHandler(access_file_handler)
        logger.setLevel(log_level)
        logger.propagate = False

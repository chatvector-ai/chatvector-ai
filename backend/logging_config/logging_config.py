import logging
import json
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime
from typing import Any, Dict

from logging_config.logging_filters import RequestIDFilter
from core.config import config  # Import settings to get LOG_FORMAT


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    Converts log records to JSON format for machine readability.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        
        # Add request_id if available (from your filter)
        if hasattr(record, 'request_id'):
            log_data['request_id'] = record.request_id
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


def setup_logging(
    log_file: str | None = None,
    access_log_file: str | None = None,
) -> None:
    """
    Logging strategy:
    - Application logs -> logs/app.log (with request_id)
    - Uvicorn access logs -> logs/access.log AND console
    - No duplicate logs
    - Supports JSON format when LOG_FORMAT=JSON is set

    When APP_ENV=test, writes to logs/test.log and logs/test_access.log
    instead of the production log files to keep test output separate from
    live server activity.
    """
    app_env = os.environ.get("APP_ENV", "production").lower()
    is_test = app_env == "test"

    if log_file is None:
        log_file = "logs/test.log" if is_test else "logs/app.log"
    if access_log_file is None:
        access_log_file = "logs/test_access.log" if is_test else "logs/access.log"

    logging.captureWarnings(True)

    # Ensure log directories exist
    log_path = Path(log_file)
    access_log_path = Path(access_log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    access_log_path.parent.mkdir(parents=True, exist_ok=True)

    # -------- FORMATTERS --------
    if config.LOG_FORMAT == "JSON":
        # Use JSON formatter for everything
        app_formatter = JSONFormatter()
        uvicorn_formatter = JSONFormatter()
    else:
        # Use existing text formatters
        app_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - "
            "[request_id=%(request_id)s] - %(message)s"
        )
        uvicorn_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        )

    # -------- HANDLERS --------
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,
        backupCount=5,
    )
    file_handler.setFormatter(app_formatter)
    file_handler.addFilter(RequestIDFilter())

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(uvicorn_formatter)

    access_file_handler = RotatingFileHandler(
        access_log_file,
        maxBytes=10_000_000,
        backupCount=5,
    )
    access_file_handler.setFormatter(uvicorn_formatter)

    log_level = getattr(logging, config.LOG_LEVEL, logging.INFO)

    # -------- ROOT LOGGER (APP LOGS) --------
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)

    # -------- UVICORN LOGGERS --------
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(console_handler)
        logger.addHandler(access_file_handler)
        logger.setLevel(log_level)
        logger.propagate = False
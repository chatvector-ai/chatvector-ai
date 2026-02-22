import logging
import json
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


def setup_logging(log_file: str = "logs/app.log") -> None:
    """
    Logging strategy:
    - Application logs -> file (with request_id)
    - Uvicorn logs -> console only
    - No duplicate logs
    - Supports JSON format when LOG_FORMAT=JSON is set
    """

    logging.captureWarnings(True)

    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

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

    # -------- ROOT LOGGER (APP LOGS) --------
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)

    # -------- UVICORN LOGGERS --------
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(console_handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
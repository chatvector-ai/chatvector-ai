import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from logging_config.logging_filters import (
    RequestIDFilter,
    AppOnlyFilter,
    UvicornOnlyFilter,
)

def setup_logging(log_file: str = "logs/app.log") -> None:
    """
    Configure application logging with request-level correlation IDs.
    Logging strategy:
    - Application logs → file only (include request_id)
    - Uvicorn / access logs → console only (no request_id)
    - Prevent duplicate logs by controlling propagation explicitly
    """

    # Route Python warnings (e.g. deprecations) through logging
    logging.captureWarnings(True)

    # Ensure the log folder exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # ============= FORMATTERS =============
    # App logs include request_id for correlation across a single request
    app_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - "
        "[request_id=%(request_id)s] - %(message)s"
    )

    # Uvicorn logs stay minimal and human-readable
    uvicorn_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s"
    )

    # ============= HANDLERS =============
    # File handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,
        backupCount=5,
    )
    file_handler.setFormatter(app_formatter)
    file_handler.addFilter(RequestIDFilter())
    file_handler.addFilter(AppOnlyFilter())

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(uvicorn_formatter)
    console_handler.addFilter(UvicornOnlyFilter())

    # ============= ROOT LOGGER =============
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # ============= UVICORN LOGGER =============
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

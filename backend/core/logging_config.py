import logging
from logging.handlers import RotatingFileHandler
from core.logging_filters import (
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

    # ============= FORMATTERS =============
    # App logs include request_id for correlation across a single request
    app_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - "
        "[request_id=%(request_id)s] - %(message)s"
    )

    # Uvicorn logs stay minimal and human-readable
    # (request_id is intentionally excluded)
    uvicorn_formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s"
    )

    # ============= HANDLERS =============
    # File handler:
    # - Receives ONLY application logs
    # - Injects request_id via RequestIDFilter
    # - Rotates to prevent unbounded growth
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10_000_000,
        backupCount=5,
    )
    file_handler.setFormatter(app_formatter)
    file_handler.addFilter(RequestIDFilter())   # inject request_id
    file_handler.addFilter(AppOnlyFilter())     # drop uvicorn logs

    # Console handler:
    # - Receives ONLY uvicorn logs (startup, access, shutdown)
    # - Keeps local dev output clean and familiar
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(uvicorn_formatter)
    console_handler.addFilter(UvicornOnlyFilter())

    # ============= ROOT LOGGER =============
    # All logs flow through the root logger first.
    # Handlers + filters decide where each record ultimately goes.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear any existing handlers to avoid duplicate output
    root_logger.handlers.clear()

    # Attach both handlers once at the root
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # ============= UVICORN LOGGER =============
    # Allow uvicorn logs to propagate to root
    # (filters on handlers determine their final destination)
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True






import logging
import logging.handlers
from core.config import config
import sys
import time
from pathlib import Path


def setup_logging():
    """Configure application logging.

    - Creates a `logs/` directory at the repository root (two parents above this file).
    - Adds a rotating file handler (max 5MB, 5 backups).
    - Adds a console handler (stdout).
    - Wires `uvicorn` loggers to use the same handlers.
    - Timestamps use local time by default; set `LOG_USE_UTC=true` to use UTC.
    """

    # Compute repo root and ensure logs directory exists
    repo_root = Path(__file__).resolve().parents[2]
    logs_dir = repo_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, config.LOG_LEVEL, logging.INFO)

    # Choose timestamp mode based on configuration
    if getattr(config, "LOG_USE_UTC", False):
        logging.Formatter.converter = time.gmtime
    else:
        logging.Formatter.converter = time.localtime

    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Console handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(fmt))
    stream_handler.setLevel(log_level)

    # Rotating file handler
    file_path = logs_dir / "app.log"
    file_handler = logging.handlers.RotatingFileHandler(
        str(file_path), maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(fmt))
    file_handler.setLevel(log_level)

    # Apply to root logger
    logging.basicConfig(level=log_level, handlers=[stream_handler, file_handler], force=True)

    # Wire uvicorn loggers
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [stream_handler, file_handler]
        lg.setLevel(log_level)
        lg.propagate = False

    logging.getLogger(__name__).debug(f"Logging configured. logs_dir={logs_dir} level={log_level}")
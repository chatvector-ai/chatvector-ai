import logging
from middleware.request_id import get_request_id

class RequestIDFilter(logging.Filter):
    """Inject request_id into application log records."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "system"
        return True

class AppOnlyFilter(logging.Filter):
    """Allow only backend (application) logs."""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith("backend")

class UvicornOnlyFilter(logging.Filter):
    """Allow only uvicorn logs."""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith("uvicorn")
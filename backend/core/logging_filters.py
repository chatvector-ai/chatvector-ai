import logging
from backend.middleware.request_id import get_request_id

class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "unknown"
        return True
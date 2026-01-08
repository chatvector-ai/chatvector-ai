# app/middleware/request_id.py
import uuid
import contextvars
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable to store request ID per request
request_id_var = contextvars.ContextVar("request_id", default=None)

def get_request_id() -> str:
    """
    Retrieve the current request ID from contextvar.
    Returns None if not set.
    """
    return request_id_var.get()

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Use incoming X-Request-ID if present, else generate
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # Store in contextvar
        request_id_var.set(request_id)
        
        # Process request
        response = await call_next(request)
        
        # Add X-Request-ID header to response
        response.headers["X-Request-ID"] = request_id
        return response
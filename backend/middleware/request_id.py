import uuid
import contextvars
from fastapi import Request, FastAPI

# Context variable to store request ID per request
request_id_var = contextvars.ContextVar("request_id", default=None)

def get_request_id() -> str | None:
    """
    Retrieve the current request ID from contextvar.
    Returns None if not set.
    """
    return request_id_var.get()


def register_request_id_middleware(app: FastAPI) -> None:
    """
    Register HTTP middleware that attaches a request-scoped correlation ID.

    This middleware ensures every request has a unique X-Request-ID that is:
    - Generated or propagated from incoming headers
    - Stored using contextvars for async-safe, per-request isolation
    - Automatically cleaned up after the request completes to prevent cross-request leakage
    - Added to the response headers for end-to-end traceability
    """

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Set context var and keep token for reset
        token = request_id_var.set(request_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # Always reset context to avoid cross-request leakage
            request_id_var.reset(token)

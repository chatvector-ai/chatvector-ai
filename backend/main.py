import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

import db
from core.config import STALE_INGESTION_STATUSES, config
from logging_config.logging_config import setup_logging
from middleware.rate_limit import limiter, rate_limit_exceeded_handler
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.request_id import register_request_id_middleware
from routes.chat import router as chat_router
from routes.documents import router as documents_router
from routes.queue import router as queue_router
from routes.root import router as root_router
from routes.status import router as status_router
from routes.upload import router as upload_router
from services.queue_service import ingestion_queue

import logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.start_time = time.time()
    # Resolve documents that were in-flight during the previous server run before
    # any workers start, so clients polling for status get a definitive answer.
    try:
        stale_doc_ids = await db.fail_stale_documents(STALE_INGESTION_STATUSES)
        if stale_doc_ids:
            logger.warning(
                f"Marked {len(stale_doc_ids)} stale document(s) as failed "
                f"(statuses: {STALE_INGESTION_STATUSES})"
            )

            # When using the Redis backend, any jobs left in the RQ queue from a
            # previous run correspond to documents that fail_stale_documents() just
            # marked as failed (since "queued"/"retrying"/etc. are all stale).
            # Clear them so workers don't pick up jobs for already-failed documents.
            if config.QUEUE_BACKEND == "redis":
                removed = ingestion_queue.clear_stale_jobs(stale_doc_ids)
                logger.info(
                    "Cleared %d stale RQ job(s) for %d failed document(s)",
                    removed,
                    len(stale_doc_ids),
                )
    except Exception:
        logger.exception("Failed to reset stale documents on startup — continuing anyway")

    await ingestion_queue.start()
    logger.info("Application startup complete.")
    yield
    await ingestion_queue.stop()
    logger.info("Application shutdown complete.")


_is_prod = config.APP_ENV.lower() == "production"
app = FastAPI(
    lifespan=lifespan,
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


async def request_validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "validation_error",
                "message": "Request validation failed",
                "fields": [
                    {"loc": list(err.get("loc", ())), "msg": err.get("msg", "")}
                    for err in exc.errors()
                ],
            }
        },
    )


app.add_exception_handler(RequestValidationError, request_validation_exception_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code, 
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None)
        )
    

    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.error(f"Unhandled exception [req_id={request_id}] for {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "internal_error",
                "message": "An unexpected error occurred."
            }
        }
    )


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

register_request_id_middleware(app)

app.include_router(root_router)
app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(queue_router)
app.include_router(status_router)

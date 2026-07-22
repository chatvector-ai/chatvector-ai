import asyncio
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
from db.migration_ledger import (
    MigrationFilesMissingError,
    MigrationLedgerError,
    MigrationLedgerSchemaError,
    validate_migration_ledger,
)
from logging_config.logging_config import setup_logging
from middleware.rate_limit import limiter, rate_limit_exceeded_handler
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.request_id import register_request_id_middleware
from routes.chat import router as chat_router
from routes.documents import router as documents_router
from routes.queue import router as queue_router
from routes.root import router as root_router
from routes.sessions import router as sessions_router
from routes.status import router as status_router
from routes.upload import router as upload_router
from services.queue_service import ingestion_queue

import logging

setup_logging()
logger = logging.getLogger(__name__)
operator_logger = logging.getLogger("uvicorn.error")

MIGRATION_LEDGER_STARTUP_ATTEMPTS = 5
MIGRATION_LEDGER_RETRY_DELAY_SECONDS = 1.0
MIGRATION_LEDGER_READ_TIMEOUT_SECONDS = 5.0


async def _read_migration_ledger_with_retry() -> list[str] | None:
    """Allow an in-progress migration a brief window to finish its ledger write."""

    for attempt in range(1, MIGRATION_LEDGER_STARTUP_ATTEMPTS + 1):
        applied_migrations: list[str] | None = None
        try:
            applied_migrations = await asyncio.wait_for(
                db.list_applied_migrations(),
                timeout=MIGRATION_LEDGER_READ_TIMEOUT_SECONDS,
            )
            validate_migration_ledger(applied_migrations)
        except (MigrationFilesMissingError, MigrationLedgerSchemaError):
            raise
        except MigrationLedgerError:
            if attempt == MIGRATION_LEDGER_STARTUP_ATTEMPTS:
                raise
        except Exception:
            if attempt == MIGRATION_LEDGER_STARTUP_ATTEMPTS:
                raise
        else:
            return applied_migrations

        await asyncio.sleep(MIGRATION_LEDGER_RETRY_DELAY_SECONDS)

    return None


def _log_operator_issue(level: int, message: str) -> None:
    """Write migration drift to both app logs and Docker-visible Uvicorn logs."""

    logger.log(level, "%s", message)
    operator_logger.log(level, "%s", message)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.start_time = time.time()

    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Set DATABASE_URL to a PostgreSQL connection string with pgvector enabled "
            "(e.g. postgresql+asyncpg://user:pass@host:5432/dbname). "
            "See backend/.env.example for configuration options."
        )

    try:
        applied_migrations = await _read_migration_ledger_with_retry()
        migration_drift = validate_migration_ledger(applied_migrations)
    except MigrationLedgerError as exc:
        _log_operator_issue(logging.ERROR, str(exc))
        raise
    except Exception as exc:
        message = (
            "Failed to read public.schema_migrations after startup retries. "
            "Check DATABASE_URL connectivity and ensure the runtime database role "
            "has SELECT permission on public.schema_migrations."
        )
        _log_operator_issue(logging.ERROR, message)
        raise RuntimeError(message) from exc

    if migration_drift.unknown_to_checkout:
        unknown = ", ".join(migration_drift.unknown_to_checkout)
        _log_operator_issue(
            logging.WARNING,
            "Database migration ledger contains entries absent from this checkout: "
            f"{unknown}. The database may be newer than this application version; "
            "verify the deployed release before continuing.",
        )
    else:
        logger.info(
            "Database migration ledger is current (%d migration(s)).",
            len(applied_migrations or ()),
        )

    if config.QUEUE_BACKEND == "redis":
        from core.clients import redis_client
        try:
            await redis_client.ping()
            logger.info("Successfully connected to Redis queue backend.")
        except Exception as e:
            logger.error(
                "Failed to connect to Redis at REDIS_URL. Ensure Redis is running "
                "or set QUEUE_BACKEND=memory for local development."
            )
            raise e

    # Resolve documents that were in-flight during the previous server run before
    # any workers start, so clients polling for status get a definitive answer.
    try:
        stale_doc_ids = await db.fail_stale_documents_global(STALE_INGESTION_STATUSES)
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

    # ── Development tenant bootstrap + auth bypass warning ───────────────────
    if config.APP_ENV.lower() in ("development", "test"):
        import os as _os

        from services.api_key_service import (
            DevelopmentTenantConfigError,
            bootstrap_development_tenant,
        )

        try:
            await bootstrap_development_tenant(config.APP_ENV)
        except DevelopmentTenantConfigError as exc:
            logger.error("%s Startup aborted.", exc)
            raise
        except Exception:
            logger.exception(
                "Failed to ensure development tenant exists. "
                "Check DATABASE_URL connectivity and that migrations 005/006 "
                "have been applied."
            )
            raise

        dev_tenant = _os.getenv("DEV_TENANT_ID", "dev").strip()
        logger.warning(
            "⚠️  Authentication bypass is ACTIVE (APP_ENV=%s). "
            "All requests are treated as tenant=%r without API-key validation. "
            "Set APP_ENV=production to enable real authentication.",
            config.APP_ENV,
            dev_tenant,
        )

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
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-Session-Id"],
)

register_request_id_middleware(app)

app.include_router(root_router)
app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(sessions_router)
app.include_router(queue_router)
app.include_router(status_router)

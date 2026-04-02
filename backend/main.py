import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

import db
from core.config import STALE_INGESTION_STATUSES, config
from logging_config.logging_config import setup_logging
from middleware.rate_limit import limiter, rate_limit_exceeded_handler
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
        stale_count = await db.fail_stale_documents(STALE_INGESTION_STATUSES)
        if stale_count:
            logger.warning(
                f"Marked {stale_count} stale document(s) as failed "
                f"(statuses: {STALE_INGESTION_STATUSES})"
            )
    except Exception:
        logger.exception("Failed to reset stale documents on startup — continuing anyway")

    await ingestion_queue.start()
    logger.info("Application startup complete.")
    yield
    await ingestion_queue.stop()
    logger.info("Application shutdown complete.")


app = FastAPI(lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_request_id_middleware(app)

app.include_router(root_router)
app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(queue_router)
app.include_router(status_router)

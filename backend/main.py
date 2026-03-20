from contextlib import asynccontextmanager

from fastapi import FastAPI

from logging_config.logging_config import setup_logging
from middleware.request_id import register_request_id_middleware
from routes.chat import router as chat_router
from routes.documents import router as documents_router
from routes.root import router as root_router
from routes.test import router as test_router
from routes.upload import router as upload_router
from services.queue_service import ingestion_queue

import logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ingestion_queue.start()
    logger.info("Application startup complete.")
    yield
    await ingestion_queue.stop()
    logger.info("Application shutdown complete.")


app = FastAPI(lifespan=lifespan)

register_request_id_middleware(app)

app.include_router(root_router)
app.include_router(test_router)
app.include_router(upload_router)
app.include_router(chat_router)
app.include_router(documents_router)

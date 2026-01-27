from fastapi import FastAPI
from routes.test import router as test_router
from routes.upload import router as upload_router
from routes.chat import router as chat_router
from logging_config.logging_config import setup_logging
from middleware.request_id import register_request_id_middleware
import logging

app = FastAPI()

logger = logging.getLogger(__name__)

setup_logging()

# request id middleware
register_request_id_middleware(app)

@app.get("/")
def root():
    logger.info("Root endpoint accessed") # Log access to root endpoint
    return {"message": "ChatVector AI Backend is Live!"} 

app.include_router(test_router) 
app.include_router(upload_router)
app.include_router(chat_router)

logger.info("Application startup complete.")
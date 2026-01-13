from fastapi import FastAPI
from backend.routes.test import router as test_router
from backend.routes.upload import router as upload_router
from backend.routes.chat import router as chat_router
from backend.core.config import Settings
from backend.core.logging_config import setup_logging
import logging


app = FastAPI()

logger = logging.getLogger(__name__)
setup_logging()

@app.get("/")
def root():
    logger.info("Root endpoint accessed") # Log access to root endpoint
    return {"message": "ChatVector AI Backend is Live!"} 

app.include_router(test_router) 
app.include_router(upload_router)
app.include_router(chat_router)

logger.info("Application startup complete.")
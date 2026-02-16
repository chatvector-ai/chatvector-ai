"""
Database Service Factory
========================

This module provides a unified interface to database operations regardless of
which backend is being used (SQLAlchemy for dev, Supabase for prod).

What it does:
- Factory pattern: Returns the correct database service based on APP_ENV
- Singleton: Service is created once and cached
- Retry wrapper: All operations automatically retry on transient failures
- Convenience exports: Other modules import these functions, not services directly

Benefits:
- Environment agnosticism: Route code doesn't know/care which DB is used
- Consistency: All DB operations get same retry behavior and logging
- Extensibility: Adding new DB backends just means new service class
- Separation of concerns: Services handle DB ops, factory handles selection,
  retry utility handles failures

Transient errors (timeouts, connection issues) auto-retry 3x.
Permanent errors (constraints, validation) fail immediately.
"""

import logging
from app.config import config
from app.utils.retry import retry_async  
from core.models import DocumentChunk

logger = logging.getLogger(__name__)

# This holds the chosen database service
db_service = None

# factory func that returns the appropriate database service based on environment
def get_db_service():
    global db_service
    
    if db_service is not None:
        return db_service
    
    if config.APP_ENV.lower() == "development":
        from app.db.sqlalchemy_service import SQLAlchemyService
        db_service = SQLAlchemyService()
        logger.info("Using SQLAlchemy database service (development)")
    else:
        from app.db.supabase_service import SupabaseService
        db_service = SupabaseService()
        logger.info("Using Supabase database service (production)")
    
    return db_service

# Create a document with retry logic for transient failures
async def create_document(filename: str) -> str:
    service = get_db_service()
    
    async def _create():
        return await service.create_document(filename)
    
    return await retry_async(
        _create,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.create_document"
    )

# Insert chunks with retry logic for transient failures
async def store_chunks_with_embeddings(
    doc_id: str, 
    chunks_with_embeddings: list[tuple[str, list[float]]]
) -> list[str]:
    service = get_db_service()
    
    async def _store():
        return await service.store_chunks_with_embeddings(doc_id, chunks_with_embeddings)
    
    return await retry_async(
        _store,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.store_chunks_with_embeddings"
    )

# Get document with retry logic for transient failures
async def get_document(doc_id: str) -> dict:
    service = get_db_service()
    
    async def _get():
        return await service.get_document(doc_id)
    
    return await retry_async(
        _get,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.get_document"
    )

# Find chunks similar to query embedding using vector search.db
async def find_similar_chunks(
    doc_id: str,
    query_embedding: list[float],
    match_count: int = 5
) -> list[DocumentChunk]:
    
    service = get_db_service()
    
    async def _find():
        return await service.find_similar_chunks(doc_id, query_embedding, match_count)
    
    return await retry_async(
        _find,
        max_retries=3,
        base_delay=1.0,
        backoff=2.0,
        func_name=f"{service.__class__.__name__}.find_similar_chunks"
    )

__all__ = [
    "get_db_service",
    "create_document", 
    "store_chunks_with_embeddings",
    "get_document",
    "find_similar_chunks",  # 👈 Add this
    "db_service",  
]


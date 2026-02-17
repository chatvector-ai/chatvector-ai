"""
Database setup for SQLAlchemy (development only)
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import config

# Use PostgreSQL for development (matching your docker-compose)
DATABASE_URL = "postgresql+asyncpg://postgres:postgres@db:5432/chatvector"

engine = create_async_engine(
    DATABASE_URL,
    echo=True,  # Log SQL queries in dev
    future=True
)

async_session = sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    """Dependency for getting database sessions."""
    async with async_session() as session:
        yield session
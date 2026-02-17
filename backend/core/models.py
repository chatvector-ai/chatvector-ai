# backend/core/models.py
from datetime import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from core.config import config

Base = declarative_base()

# async engine
DATABASE_URL = config.DATABASE_URL
async_engine = create_async_engine(
    DATABASE_URL,
    echo=True,
)

async_session = sessionmaker(
    async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="uploaded")
    failed_stage = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    chunks_total = Column(Integer, nullable=False, default=0)
    chunks_processed = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    chunk_text = Column(String, nullable=False)
    embedding = Column(Vector(3072), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

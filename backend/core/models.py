# backend/core/models.py
from datetime import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

from core.config import get_embedding_dim

Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="uploaded")
    chunks = Column(JSONB, nullable=False, default=lambda: {"total": 0, "processed": 0})
    error = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    chunk_text = Column(String, nullable=False)
    embedding = Column(Vector(get_embedding_dim()), nullable=False)
    chunk_index = Column(Integer, nullable=False, default=0)
    page_number = Column(Integer, nullable=True)
    character_offset_start = Column(Integer, nullable=False, default=0)
    character_offset_end = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

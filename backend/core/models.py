# backend/core/models.py
from datetime import datetime
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

from core.config import get_embedding_dim

Base = declarative_base()


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(String(255), ForeignKey("tenants.id"), nullable=False, index=True)
    prefix = Column(String(16), nullable=False, unique=True, index=True)
    key_hash = Column(String(64), nullable=False)
    status = Column(String(50), nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name = Column(String, nullable=False)
    tenant_id = Column(String(255), nullable=True, index=True)
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


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String, nullable=False, index=True)
    tenant_id = Column(String, nullable=True, index=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SessionRecord(Base):
    """Durable session metadata stored in PostgreSQL."""

    __tablename__ = "sessions"

    id = Column(String(255), primary_key=True)
    tenant_id = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)


class SessionDocument(Base):
    """Join table binding documents to sessions."""

    __tablename__ = "session_documents"

    session_id = Column(
        String(255),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    document_id = Column(String(255), primary_key=True, nullable=False)

# Architecture Overview

System design details and architectural decisions

## Table of Contents

- [System Design](#system-design)
- [Database Strategy Pattern](#database-strategy-pattern)
- [Development vs Production](#development-vs-production)
- [Retry Logic](#retry-logic)
- [Vector Search Design](#vector-search-design)
- [Design Principles](#design-principles)
- [Extension Path](#extension-path)
- [Why This Architecture](#why-this-architecture)

---

## System Design

ChatVector uses a layered architecture:

API Layer → Service Layer → Database Abstraction → PostgreSQL (pgvector)

The system is designed for:

- Production parity
- Clean separation of concerns
- Resilience against transient failures
- Extensibility

---

## Database Strategy Pattern

An abstract base class defines the contract:

- `DatabaseService`

Two implementations:

- `SQLAlchemyService` (development)
- `SupabaseService` (production)

Selected via environment-aware factory in:

```
app/db/__init__.py
```

This ensures:

- No direct DB coupling in business logic
- Environment-specific behavior isolated
- Easy extension for future backends

---

## Development vs Production

| Environment | Database                  | Implementation    |
| ----------- | ------------------------- | ----------------- |
| Development | PostgreSQL (local Docker) | SQLAlchemyService |
| Production  | Supabase (PostgreSQL)     | SupabaseService   |

SQLite was intentionally removed to ensure:

- Production parity
- Consistent vector behavior
- Identical query semantics

---

## Retry Logic

All database operations are wrapped with retry logic.

Purpose:

- Handle transient connection failures
- Protect against Supabase network hiccups
- Improve production resilience

Retries are applied at the service layer, not the API layer, to maintain separation of concerns.

---

## Vector Search Design

- PostgreSQL with `pgvector`
- Embedding dimension: `3072` (Gemini-compatible)
- `ivfflat` indexing supported
- Cosine similarity search

Schema overview:

```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  file_name TEXT,
  created_at TIMESTAMP DEFAULT NOW(),
  status VARCHAR(50) DEFAULT 'processing'
);

CREATE TABLE document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id),
  chunk_text TEXT,
  embedding vector(3072),
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Design Principles

### 1. Production Parity

Local development mirrors production database behavior.

### 2. Environment Isolation

Environment selection happens at the factory layer.

### 3. Abstraction Boundaries

No direct DB calls outside `app.db`.

### 4. Async-First

All database operations are async.

### 5. Failure Resilience

Transient failures are handled automatically.

---

## Extension Path

Future improvements may include:

- Multi-tenant support
- Background task queue
- Embedding provider abstraction
- Observability and metrics
- Caching layer
- Read replicas

The current abstraction layer supports these extensions without major refactors.

---

## Why This Architecture

This project demonstrates:

- Clean service abstraction
- Production-ready database design
- Resilient error handling
- Contributor-friendly extensibility
- Clear separation between operational and architectural concerns

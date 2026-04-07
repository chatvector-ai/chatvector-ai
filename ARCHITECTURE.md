# Architecture Overview

System design details and architectural decisions for ChatVector.

## Table of Contents

- [System Design](#system-design)
- [Database Strategy Pattern](#database-strategy-pattern)
- [Development vs Production](#development-vs-production)
- [Ingestion Pipeline](#ingestion-pipeline)
- [Ingestion Queue](#ingestion-queue)
- [Chunking Strategies](#chunking-strategies)
- [Query Transformations](#query-transformations)
- [Prompt Configuration](#prompt-configuration)
- [Retry Logic & Resilience](#retry-logic--resilience)
- [Rate Limiting](#rate-limiting)
- [Security Hardening](#security-hardening)
- [Logging & Observability](#logging--observability)
- [Health Checks](#health-checks)
- [Vector Search Design](#vector-search-design)
- [Python Client SDK](#python-client-sdk)
- [Design Principles](#design-principles)
- [Extension Path](#extension-path)

---

## System Design

ChatVector uses a layered architecture:
Client → API Layer → Service Layer → Database Abstraction → PostgreSQL (pgvector)

The system is designed for:
- Production parity between development and production environments
- Clean separation of concerns across layers
- Resilience against transient failures
- Extensibility without major refactors

---

## Database Strategy Pattern

An abstract base class defines the contract:
- `DatabaseService` (`db/base.py`)

Two implementations:
- `SQLAlchemyService` — development (local PostgreSQL via asyncpg)
- `SupabaseService` — production (Supabase-hosted PostgreSQL)

Selected via an environment-aware factory in `backend/db/__init__.py`.
All DB operations are wrapped with retry logic at the factory layer.

This ensures:
- No direct DB coupling in business logic
- Environment-specific behavior isolated to the implementation layer
- Easy extension for future backends

---

## Development vs Production

| Environment | Database                  | Implementation    |
| ----------- | ------------------------- | ----------------- |
| Development | PostgreSQL (local Docker) | SQLAlchemyService |
| Production  | Supabase (PostgreSQL)     | SupabaseService   |

SQLite was intentionally removed to ensure production parity, consistent
vector behavior, and identical query semantics across environments.

---

## Ingestion Pipeline

`POST /upload` returns in under 500ms regardless of file size. The heavy
work — text extraction, chunking, embedding, and storage — happens in the
background via an async queue.

### Status flow
```
queued → extracting → chunking → embedding → storing → completed
                                                      ↘ failed (→ DLQ after max retries)
```

### Upload flow
```
Client                   API                       Worker pool
  │                       │                             │
  │── POST /upload ───────▶│                             │
  │                       │ validate file               │
  │                       │ sanitize filename           │
  │                       │ validate MIME content       │
  │                       │ create document (DB)        │
  │                       │ update status → "queued"    │
  │                       │ enqueue(job)                │
  │◀─ 202 {doc_id,        │                             │
  │    queue_position} ───│                             │
  │                       │            pick up job ─────▶
  │                       │            update → extracting
  │                       │            update → chunking
  │                       │            rate-limit token
  │                       │            update → embedding
  │                       │            update → storing
  │                       │            update → completed
```

---

## Ingestion Queue

An async in-memory `asyncio.Queue` decouples upload from processing.

**Key properties:**
- Bounded queue (`QUEUE_MAX_SIZE`, default 100) — uploads beyond capacity return 503
- Worker pool (`QUEUE_WORKER_COUNT`, default 3, max 5)
- Token bucket rate limiter (`QUEUE_EMBEDDING_RPS`, default 2.0/sec) — caps Gemini embedding API calls across all workers
- Exponential backoff with jitter between job retries
- 4xx `UploadPipelineError` failures (e.g. no text extracted) go directly to DLQ without consuming retries
- Transient failures retry up to `QUEUE_JOB_MAX_RETRIES` times, then move to DLQ

**Dead-letter queue (DLQ):**
- In-memory only — cleared on server restart
- Lightweight records only (no file bytes)
- Inspectable via `GET /queue/stats`
- Document `status` persisted to DB as `failed` for durable inspection

**On server restart:**
Documents left in any in-progress state are bulk-updated to `failed`
before workers start accepting new jobs.

> **Note:** The queue will be replaced with Redis (#123) for job
> durability and multi-instance support.

---

## Chunking Strategies

Chunking is configurable via `CHUNKING_STRATEGY` env var.

| Strategy | Description |
| --- | --- |
| `fixed` (default) | Fixed-size chunks with overlap via `RecursiveCharacterTextSplitter` |
| `paragraph` | Splits on blank lines and heading boundaries; respects `CHUNK_SIZE` as a ceiling |
| `semantic` | Sentence-aware grouping using NLTK tokenizer with regex fallback |

All strategies populate chunk metadata: `page_number`, `character_offset_start`,
`character_offset_end`, `chunk_index`, and detected `heading` where available.

Implemented via a strategy pattern in `backend/services/ingestion_pipeline.py` —
new strategies can be added without touching pipeline orchestration logic.

---

## Query Transformations

An optional transformation layer sits between the user's question and
vector search. Controlled via `QUERY_TRANSFORMATION_ENABLED` and
`QUERY_TRANSFORMATION_STRATEGY`.

| Strategy | Description |
| --- | --- |
| `rewrite` | LLM rephrases the question for better retrieval |
| `expand` | Generates 2 alternative phrasings; retrieves and deduplicates across all |
| `stepback` | Identifies the broader concept; retrieves on both original and broader query |

All strategies degrade gracefully — if the LLM call fails, the original
question is used unchanged. Implemented in `backend/services/query_service.py`.

---

## Prompt Configuration

The system prompt and LLM parameters are externalized for operator
customization without code changes.

- `SYSTEM_PROMPT_PATH` — path to system prompt file (default: `backend/prompts/default_system.txt`)
- `LLM_TEMPERATURE` — generation temperature (default: 0.2)
- `LLM_MAX_OUTPUT_TOKENS` — max output tokens (default: 1024)

Example domain prompts are provided under `backend/prompts/examples/`
for legal, academic, and internal knowledge base use cases.

---

## Retry Logic & Resilience

All external I/O is wrapped with retry logic via `backend/utils/retry.py`.

**`retry_async` features:**
- Per-attempt timeout via `asyncio.wait_for` (default 30s)
- Exponential backoff with full jitter — `random.uniform(0, cap)` prevents thundering herd
- `asyncio.TimeoutError` caught by type and always treated as transient
- 429/rate-limit errors from Gemini detected by type (`APIError`) before string matching
- Non-transient errors (4xx validation failures) fail fast without retry

**Timeout configuration:**
| Surface | Timeout | Mechanism |
| --- | --- | --- |
| DB operations | 10s per attempt | `retry_async(timeout=10.0)` |
| Embedding calls | 30s per attempt | `retry_async(timeout=30.0)` |
| LLM HTTP client | 60s | `HttpOptions(timeout=LLM_HTTP_TIMEOUT_MS)` |
| SQLAlchemy pool | 30s checkout | `pool_timeout` on engine |
| SQLAlchemy queries | 30s | `command_timeout` on asyncpg |
| Supabase HTTP | 30s | `ClientOptions` timeouts |
| Health checks | 10s (embed), 15s (LLM) | `asyncio.wait_for` |

---

## Rate Limiting

Per-IP HTTP rate limiting via `slowapi` on all public endpoints.

| Endpoint | Default limit |
| --- | --- |
| `POST /upload` | 20/hour |
| `POST /chat` | 30/minute |
| `POST /chat/batch` | 10/minute |
| `GET /status` | 10/minute |
| `GET /queue/stats` | 10/minute |
| `GET /documents/{id}/status` | 120/minute |
| `DELETE /documents/{id}` | 60/hour |

All limits are configurable via env vars (`RATE_LIMIT_*`).
429 responses return `{"detail": {"code": "rate_limited", "message": "..."}}`.

Storage is in-memory for single-instance deployments. Migration to
Redis-backed storage is planned when #123 lands.

---

## Security Hardening

**Security headers** — applied to every response via `SecurityHeadersMiddleware`:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `X-XSS-Protection: 0`

**CORS** — explicit allowlist for methods and headers; wildcard origins
rejected at startup when `allow_credentials=True`.

**Upload security:**
- Filename sanitized before storage, logging, and queue — strips path
  components, control characters, and caps length
- PDF validated against `%PDF-` magic bytes
- TXT validated as UTF-8 or cp1254 before processing

**Input validation** — Pydantic field bounds on all chat endpoints:
`max_length=2000` on questions, `le=20` on `match_count`, `max_length=20`
on batch queries.

**OpenAPI docs** — `/docs`, `/redoc`, and `/openapi.json` disabled when
`APP_ENV=production`.

**Error handling** — raw exception text never returned to clients. A global
exception handler returns `{"detail": {"code": "internal_error", "message": "..."}}`.

---

## Logging & Observability

- Structured JSON logging via `logging_config/logging_config.py`
  (`LOG_FORMAT=JSON`)
- Request ID middleware injects a unique ID per request for end-to-end
  log tracing
- Application logs written to `logs/app.log` (rotating, 10MB × 5)
- Uvicorn access logs written to `logs/access.log` (separate file)
- Both log streams also written to stdout for container-friendly collection
- Integration guides for CloudWatch, DataDog, ELK, and stdout-based
  platforms in `backend/docs/logging-integrations.md`

---

## Health Checks

`GET /status` reports health for all system components:

| Component | Check | Cached |
| --- | --- | --- |
| API | Always online if responding | No |
| Database | Live `SELECT 1` + document count | No |
| Embeddings | Test embedding call | Yes (TTL: `HEALTH_CHECK_CACHE_TTL_SECONDS`, default 60s) |
| LLM | Test generation call | Yes (same TTL) |

All three checks run concurrently via `asyncio.gather`. Health checks
never block startup or crash the service.

The embedding and LLM checks are cached independently — a failing check
is still retried after TTL expires. Each result includes `cached` and
`checked_at` fields so operators can distinguish live vs cached results.

---

## Vector Search Design

- PostgreSQL with `pgvector` extension
- Embedding dimension: `3072` (Gemini `gemini-embedding-001`)
- Cosine similarity search via `<=>` operator
- `ivfflat` indexing supported

### Schema
```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  file_name TEXT,
  status VARCHAR(50) DEFAULT 'queued',
  chunks JSONB,
  error JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP
);

CREATE TABLE document_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  chunk_text TEXT,
  embedding vector(3072),
  chunk_index INTEGER,
  page_number INTEGER,
  character_offset_start INTEGER,
  character_offset_end INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Python Client SDK

A lightweight Python SDK wraps the HTTP API for clean programmatic access.
```python
from chatvector import ChatVectorClient

with ChatVectorClient("http://localhost:8000") as client:
    doc = client.upload_document("report.pdf")
    client.wait_for_ready(doc.document_id, timeout=90)
    answer = client.chat("What are the key findings?", doc.document_id)
    print(answer.answer)
```

**Features:**
- Typed dataclass response models
- Retry with exponential backoff and jitter
- `Retry-After` header respected on 429 responses
- Typed exception hierarchy: `ChatVectorAuthError`, `ChatVectorRateLimitError`,
  `ChatVectorTimeoutError`, `ChatVectorAPIError`
- Context manager support
- `wait_for_ready()` polling helper

Install: `pip install ./sdk/python`

---

## Design Principles

### 1. Production Parity
Local development mirrors production database behavior exactly.

### 2. Environment Isolation
Environment selection happens at the factory layer — business logic
never makes environment decisions directly.

### 3. Abstraction Boundaries
No direct DB calls outside `db/__init__.py`. No direct HTTP calls
outside service modules.

### 4. Async-First
All database and external service operations are async.

### 5. Failure Resilience
Transient failures handled automatically via retry with backoff and
jitter. Timeouts enforced at every I/O boundary.

### 6. Security by Default
Input validated at schema layer. Errors sanitized before client
responses. Security headers on every response.

---

## Extension Path

The current architecture supports these extensions without major refactors:

- **Pluggable LLM & embedding providers** — Gemini, OpenAI, Ollama
  (tracked in open issue)
- **Redis-backed queue** — drop-in replacement for in-memory queue (#123)
- **Authentication & multi-tenancy** — Phase 3
- **Streaming LLM responses** — Server-Sent Events, Phase 3
- **Specialized pipelines** — legal, academic, code document handling
- **Read replicas** — supported by existing DB abstraction layer
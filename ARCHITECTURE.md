# Architecture Overview

System design details and architectural decisions for ChatVector.

## Table of Contents

- [System Design](#system-design)
- [Database Strategy Pattern](#database-strategy-pattern)
- [Schema migrations](#schema-migrations)
- [Development vs Production](#development-vs-production)
- [Ingestion Pipeline](#ingestion-pipeline)
- [Ingestion Queue](#ingestion-queue)
- [Chunking Strategies](#chunking-strategies)
- [Query Transformations](#query-transformations)
- [Prompt Configuration](#prompt-configuration)
- [Retry Logic & Resilience](#retry-logic--resilience)
- [Rate Limiting](#rate-limiting)
- [Authentication & Multi-Tenancy](#authentication--multi-tenancy)
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

One implementation:
- `SQLAlchemyService` — all environments (PostgreSQL/pgvector via asyncpg)

`DATABASE_URL` controls the target PostgreSQL instance. Any PostgreSQL host with pgvector enabled is supported: local Docker, managed services (Neon, RDS, Cloud SQL, Supabase Postgres via direct connection string), or self-hosted.

The factory in `backend/db/__init__.py` always returns `SQLAlchemyService`. All DB operations are wrapped with retry logic at the factory layer.

This ensures:
- No direct DB coupling in business logic
- Consistent behavior across development, test, and production
- Hybrid retrieval (pgvector + PostgreSQL full-text) works in all environments

**Document deletion:** Removing a document and its rows in `document_chunks` is atomic — `SQLAlchemyService.delete_document()` runs both deletes in a single ORM transaction, preventing orphaned chunks on failure. The legacy `delete_document_atomic` RPC (`backend/db/init/003_atomic_delete.sql`) is retained in the database schema for backward compatibility but is not called by current runtime code.

### Schema migrations

DDL changes ship as numbered SQL files in `backend/db/init/`
(e.g. `008_schema_migrations.sql`). Files are applied in lexical sort order. CI runs
the full set before tests; Docker applies them only on first volume init;
existing production volumes require manual `psql -v ON_ERROR_STOP=1 -f` for
new files.

Migration `008_schema_migrations.sql` creates `schema_migrations` and records a
baseline for migrations `001` through `008`. Later migration files record their
own filename as their final operation before `COMMIT`, atomically with the
schema change, using an idempotent `ON CONFLICT` insert.
At startup, the application validates the ledger table contract and compares the
sorted SQL filenames with its rows. A missing or malformed ledger table, or a
missing file row, stops startup with operator-facing instructions; ledger-only
rows warn that the database may be newer than the running checkout. This
validation is read-only and never applies migrations.

The project does not use Alembic. Contributors add the next `NNN_*.sql` file,
update SQLAlchemy models to match, and document operator upgrade steps in the PR.
Full workflow (naming, CI/Docker/local apply, upgrading existing databases, and
ledger inspection) is in
[DEVELOPMENT.md — Database migrations](DEVELOPMENT.md#database-migrations).

---

## LLM & Embedding Providers

An abstract base class defines the contract for each service type:

- `EmbeddingProvider` — `async def embed(texts) -> list[list[float]]`
- `LLMProvider` — `async def generate(prompt, ...) -> str`

Multiple implementations:

- `GeminiEmbeddingProvider` / `GeminiLLMProvider` (default)
- `OpenAIEmbeddingProvider` / `OpenAILLMProvider`
- `OllamaEmbeddingProvider` / `OllamaLLMProvider`
- `VoyageEmbeddingProvider` (embedding-only)
- `AnthropicLLMProvider` (LLM-only)

Selected via environment variables (`LLM_PROVIDER`, `EMBEDDING_PROVIDER`) through factory functions in:

```
backend/services/providers/__init__.py
```

Providers map SDK-specific errors to common exceptions so services stay provider-agnostic.

Switching embedding providers requires a fresh database (`docker compose down -v`) because different models produce different vector dimensions and incompatible vector spaces.

---

## Development vs Production

| Environment | Database                                    | Implementation    |
| ----------- | ------------------------------------------- | ----------------- |
| Development | PostgreSQL (local Docker via DATABASE_URL)  | SQLAlchemyService |
| Test        | PostgreSQL (local Docker via DATABASE_URL)  | SQLAlchemyService |
| Production  | PostgreSQL/pgvector (any host, DATABASE_URL) | SQLAlchemyService |

`APP_ENV` controls auth bypass, docs suppression, queue backend defaults, and production behavior — but no longer selects the database implementation. `DATABASE_URL` is the single configuration point for the database in all environments.

SQLite was intentionally excluded to ensure production parity, consistent vector behavior, and identical query semantics across environments.

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

> **Note:** The default queue is in-memory for local development. In production
> (`APP_ENV=production`), the Redis-backed queue is the default for job durability
> and multi-instance support. Set `QUEUE_BACKEND=memory` explicitly to override.

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
- `max_retries` means retries *after* the first attempt — `max_retries=3` makes 4 total attempts

**Timeout configuration:**
| Surface | Timeout | Mechanism |
| --- | --- | --- |
| DB operations | 10s per attempt | `retry_async(timeout=10.0)` |
| Embedding calls | 30s per attempt | `retry_async(timeout=30.0)` |
| LLM HTTP client | 60s | `HttpOptions(timeout=LLM_HTTP_TIMEOUT_MS)` |
| SQLAlchemy pool | 30s checkout | `pool_timeout` on engine |
| SQLAlchemy queries | 30s | `command_timeout` on asyncpg |
| Health checks | 10s (embed), 15s (LLM) | `asyncio.wait_for` |

---

## Rate Limiting

Per-tenant HTTP rate limiting via `slowapi` on all authenticated API routes.
The authenticated tenant ID (resolved by `require_auth`) is the primary
rate-limit key. In development/test, optional IP fallback applies only when
`RATE_LIMIT_DEV_IP_FALLBACK=true` and no tenant is present on the request.
Production never silently falls back to IP-based limiting.

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
Rate-limit events are logged with tenant ID and path — raw API keys are never logged.

Storage is in-memory for single-instance deployments. Redis-backed
rate limit storage across multiple API workers remains planned for a
future Phase 3 follow-up.

---

## Authentication & Multi-Tenancy

Protected API routes require authentication via the `require_auth` FastAPI
dependency (`backend/core/auth.py`).

**Production (`APP_ENV=production`)**

- Clients must send `Authorization: Bearer cv_live_<prefix>.<secret>`
- API keys resolve to exactly one tenant via `validate_api_key`
- Tenant identity comes from authentication — not from request bodies or query params
- Missing, malformed, or revoked keys return `401` with structured error codes
- Tenants and API keys are **not** auto-created in production

**Development / test (`APP_ENV=development` or `test`)**

- Authentication is bypassed; all requests are attributed to `DEV_TENANT_ID` (default: `dev`)
- Startup automatically ensures the development tenant row exists (idempotent)
- No API key is required locally

**Bootstrap production credentials (run once per environment):**

```bash
python -m backend.cli create-tenant-key --tenant "My Org" --tenant-id my-org
```

The raw key is printed once and never stored. Set it in all API clients as the Bearer token.

**Auth non-goals:** ChatVector does not provide user login/signup, OAuth, RBAC, billing, admin dashboards, or an API-key management UI. Keys are created via CLI (`python -m backend.cli create-tenant-key`) or direct DB updates; optional `external_user_id` mapping for developer-side identity is on the roadmap.

**Session persistence:** All session state is now fully durable. Chat message turns are stored in `chat_messages`. Session metadata (`id`, `tenant_id`, `created_at`, `last_active`) is stored in the `sessions` table and document bindings are stored in `session_documents` — both introduced by migration `007_sessions.sql`. `backend/services/session_service.py` reads and writes exclusively through `SQLAlchemyService`; the previous in-memory `_SESSIONS` dict has been removed. Sessions survive backend restarts and are shared across all Uvicorn workers (`docker-compose.prod.yml` runs `--workers 2`).

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
on batch queries. Document IDs (`doc_id`, `document_id`) are validated
as UUIDs at the route layer — invalid values return 422 before reaching
the service or DB layer.

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

**Retrieval pipeline (shipped):**

- **Scopes** — `session` (default: documents bound to the session) or `tenant` (all tenant documents)
- **Hybrid retrieval** — pgvector cosine similarity + PostgreSQL full-text search, merged via Reciprocal Rank Fusion (RRF); toggle with `HYBRID_RETRIEVAL_ENABLED`
- **Reranking** — deterministic similarity + lexical-overlap baseline reranker after fusion
- **Query transformations** — optional rewrite, expand, and stepback steps using session history context
- **Citation metadata** — each source includes collapsed `score` and `score_type` (`vector`, `hybrid_rrf`, or `reranked`); per-component score breakdown is not yet exposed

- PostgreSQL with `pgvector` extension
- Embedding dimension: auto-detected from the configured provider/model (e.g. Gemini → 3072, OpenAI → 1536, Ollama nomic-embed-text → 768)
- Cosine similarity search via `<=>` operator
- `ivfflat` indexing supported

**Legacy SQL functions:** `match_chunks()` and `delete_document_atomic()` exist in
`backend/db/init/` for databases that already applied those migrations. Current
runtime code uses native SQLAlchemy/pgvector queries and ORM transactions — these
RPCs are not called. Safe to leave installed; do not rely on them for new deployments.

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
  embedding vector,
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

with ChatVectorClient("http://localhost:8000", api_key="cv_live_...") as client:
    doc = client.upload_document("report.pdf")
    client.wait_for_ready(doc.document_id, timeout=90)

    session = client.create_session()
    answer = client.chat("What are the key findings?", doc.document_id, session_id=session.id)
    print(answer.answer, answer.latency_ms, answer.model)

    for event in client.stream_chat("Summarize briefly.", doc.document_id, session_id=session.id):
        if event.type == "complete":
            print(event.sources, event.latency_ms)
```

**Features:**
- Upload, status polling, `wait_for_ready`, non-streaming chat, batch chat
- Session management (`create_session`, `list_sessions`, `delete_session`)
- Streaming chat (`stream_chat`) with typed `token` and `complete` events
- Retrieval scope options (`session` / `tenant`)
- Typed dataclass response models with citation `score` and `score_type`
- Retry with exponential backoff and jitter
- `Retry-After` header respected on 429 responses
- Typed exception hierarchy: `ChatVectorAuthError`, `ChatVectorRateLimitError`,
  `ChatVectorTimeoutError`, `ChatVectorAPIError`
- Context manager support

**Current gaps:** no async client; no ingestion SSE client (document status stream is HTTP/SSE only); no per-component retrieval score breakdown in SDK models.

Install: `pip install ./sdk/python` — see [sdk/python/README.md](sdk/python/README.md)

---

## Design Principles

### 1. Production Parity
Local development mirrors production database behavior exactly.

### 2. Environment Isolation
Environment-specific behavior (auth bypass, queue backend, docs exposure)
is resolved at configuration and middleware layers — business logic never
branches on deployment mode directly.

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

- ~~Pluggable LLM & embedding providers~~ (done — see LLM & Embedding Providers)
- ~~Redis-backed queue~~ (done — production default when `APP_ENV=production`; in-memory for local dev)
- ~~Streaming LLM responses~~ (done — SSE at `/chat/stream` with structured `complete` events)
- ~~Authentication & multi-tenancy~~ (done — Bearer API-key auth, tenant isolation, per-tenant rate limits)
- ~~Python SDK parity~~ (done — sessions, streaming, retrieval scopes)
- **Specialized pipelines** — legal, academic, code document handling
- **Read replicas** — supported by existing DB abstraction layer

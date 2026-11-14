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
- [Horizontal API Scaling](#horizontal-api-scaling)
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

The factory in `backend/db/__init__.py` always returns `SQLAlchemyService`. Most DB operations are wrapped with selective retry logic at the factory layer; non-idempotent chat/session writes are intentionally excluded. See [DEVELOPMENT.md — Where retries apply](DEVELOPMENT.md#where-retries-apply).

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

### Embedding Cache

An optional Redis-backed cache sits in front of the embedding provider call
in `services/embedding_service.get_embeddings()`, off by default
(`ENABLE_EMBEDDING_CACHE=false`). When disabled, behavior is byte-identical
to having no cache — no Redis calls occur.

When enabled:

- Cache key hashes `(EMBEDDING_PROVIDER, provider.model_name, text)` under
  `EMBEDDING_CACHE_KEY_PREFIX` (default `chatvector:embedcache`) —
  changing the provider or model can never return a vector produced by a
  different model, since the key changes with it.
- Values are stored as JSON-encoded float lists; a cache hit returns the
  exact bytes stored on a prior miss. `EMBEDDING_CACHE_TTL_SECONDS` controls
  expiry (`0`, the default, means no expiry).
- Any Redis error (down, unreachable, timeout) is caught and logged as a
  warning; the request falls through to the real provider call — the cache
  never fails a request. Cache Redis operations use
  `EMBEDDING_CACHE_REDIS_TIMEOUT_SEC` (default 0.25s), not the general
  `REDIS_SOCKET_TIMEOUT_SEC`, so a sick cache cannot stall embedding calls.
- `EMBEDDING_CACHE_INCLUDE_TENANT` optionally folds `tenant_id` into the key
  for deployments where embedding text could be cross-tenant sensitive
  under a shared Redis instance. This only changes the cache key — it is
  not a second ACL system.
- `probe_embedding_health` (the `/status` sub-check) always bypasses the
  cache and calls the real provider directly.
- Eval/benchmark tooling must not set `ENABLE_EMBEDDING_CACHE=true` in its
  own process environment unless it specifically wants cached vectors —
  documented coordination point; no such runner exists in this repo yet.

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
- Redis backend capacity is an approximate bound under highly concurrent enqueues; the in-memory queue enforces capacity atomically within the process
- Worker pool (`QUEUE_WORKER_COUNT`, default 3, max 5)
- Token bucket rate limiter (`QUEUE_EMBEDDING_RPS`, default 2.0/sec) — caps embedding HTTP batches per API process across all queue workers
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
before workers start accepting new jobs. Multiple API replicas compete for a
Redis lock (`chatvector:stale-reconcile-lock`) so only one instance runs
`fail_stale_documents_global`. Losers skip reconciliation entirely.

> **Note:** The default queue is in-memory for local development. In production
> (`APP_ENV=production`), the Redis-backed queue is the default for job durability
> across API restarts. Set `QUEUE_BACKEND=memory` explicitly to override.
>
> **Production topology:** Each API container still runs `uvicorn --workers 1`.
> Set `MULTI_API_INSTANCE=true` to run more than one container. Redis/RQ worker
> threads provide ingestion concurrency **within each process**. Concurrency
> settings such as `QUEUE_WORKER_COUNT`, `RETRIEVAL_MAX_CONCURRENCY`, DB pool
> sizes, and `QUEUE_EMBEDDING_RPS` are **per-instance caps**, not cluster-wide
> limits.
>
> **Upload artifacts:** Redis jobs carry an `artifact_uri` (`documents.artifact_uri`)
> instead of file bytes. `ARTIFACT_STORAGE=local` (default) writes `QUEUE_SPILL_DIR`
> and still needs a shared disk. `ARTIFACT_STORAGE=s3` is required when
> `MULTI_API_INSTANCE=true` so a worker without the API host's disk can fetch
> the payload. Artifacts are deleted after successful ingest or a terminal
> failure; S3 objects are also TTL-marked.

---

## Chunking Strategies

Chunking is configurable via `CHUNKING_STRATEGY` env var.

| Strategy | Description |
| --- | --- |
| `fixed` (default) | Fixed-size chunks with overlap via `RecursiveCharacterTextSplitter` |
| `paragraph` | Splits on blank lines and heading boundaries; respects `CHUNK_SIZE` as a ceiling |
| `semantic` | Sentence-aware grouping using NLTK tokenizer with regex fallback |

All strategies produce in-memory chunk metadata during ingestion: `page_number`,
`character_offset_start`, `character_offset_end`, and `chunk_index`. Paragraph
and semantic strategies may also detect a `heading` while splitting, but that
value is chunking-internal only — it is not persisted on `document_chunks` and
is not part of the API or SDK citation contract (`file_name`, `page_number`,
`chunk_index`, scores). Character offsets and PDF page boundaries refer to the
same cleaned document text produced after extraction normalization.

Implemented via a strategy pattern in `backend/services/ingestion_pipeline.py` —
new strategies can be added without touching pipeline orchestration logic.

---

## Query Transformations

An optional transformation layer sits between the user's question and
vector search. Controlled via `QUERY_TRANSFORMATION_ENABLED` and
`QUERY_TRANSFORMATION_STRATEGY`.

Follow-up resolution is separate from those strategies. With
`HISTORY_AWARE_RETRIEVAL_DEFAULT=true` (the default), a deterministic gate
may rewrite a dependent follow-up into a standalone retrieval query even
when rewrite / expand / step-back are off. Already-standalone questions and
explicit topic switches skip that extra LLM call. Setting the default to
`false` restores the previous coupling: resolution runs only when query
transformation is enabled, and then for every non-empty history window.

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
- `PROMPT_PERSONA` — response style preset (default: `default`)
- `LLM_TEMPERATURE` — generation temperature (default: 0.2)
- `LLM_MAX_OUTPUT_TOKENS` — max output tokens (default: 1024)

### Response personas

`PROMPT_PERSONA` selects a server-side system prompt style for answer
generation. Supported values:

- `default` — concise RAG assistant (`backend/prompts/default_system.txt`)
- `concise` — extreme brevity, bullet lists
- `conversational` — warm, approachable tone
- `academic` — formal, scholarly synthesis
- `technical` — engineering-focused, code-aware

When `PROMPT_PERSONA=default`, the canonical prompt is
`backend/prompts/default_system.txt`. Other personas load from
`backend/prompts/personas/{persona}.txt`.

`SYSTEM_PROMPT_PATH`, when set, takes precedence over `PROMPT_PERSONA`
and loads a custom prompt file directly.

Invalid `PROMPT_PERSONA` values log a warning at startup and fall back
to `default`.

Example domain prompts are provided under `backend/prompts/examples/`
for legal, academic, and internal knowledge base use cases.

---

## Retry Logic & Resilience

Selected backend I/O paths use shared retry logic via `backend/utils/retry.py`.
See [DEVELOPMENT.md — Retry behavior](DEVELOPMENT.md#retry-behavior) for the
full cross-surface contract and audit checklist.

**`retry_async` features:**
- Per-attempt timeout via `asyncio.wait_for` (DB: `SQLALCHEMY_STATEMENT_TIMEOUT_SEC + 5`)
- `retry_on_timeout=False` on non-idempotent DB writes
- Exponential backoff with full jitter — `random.uniform(0, cap)` prevents thundering herd
- `asyncio.TimeoutError` retried by default except when `retry_on_timeout=False`
- Provider rate limits, timeouts, and connection errors detected by structured exception types
- Non-transient errors (4xx validation failures, generic `ProviderError`) fail fast without retry
- `max_retries` means retries *after* the first attempt — `max_retries=3` makes 4 total attempts
- OpenAI/Anthropic SDK internal retries disabled (`max_retries=0`); backend owns retry policy

**Where retries apply:**
- DB factory operations (with per-operation exceptions documented in DEVELOPMENT.md)
- Embedding and non-streaming LLM answer generation use shared defaults (`DEFAULT_MAX_RETRIES=3`)
- Streaming LLM responses are not retried after bytes may have started
- Ingestion queue retries only transient failures; capacity-safe requeue (DLQ when full)

**Timeout configuration:**
| Surface | Timeout | Mechanism |
| --- | --- | --- |
| DB operations (outer) | `SQLALCHEMY_STATEMENT_TIMEOUT_SEC + 5` | `retry_async` + `asyncio.wait_for` |
| DB operations (asyncpg) | `SQLALCHEMY_STATEMENT_TIMEOUT_SEC` | asyncpg client `command_timeout` (not server `statement_timeout`) |
| Embedding calls | `EMBEDDING_HTTP_TIMEOUT_SEC` | provider HTTP client + outer `retry_async` |
| LLM HTTP client | `LLM_HTTP_TIMEOUT_MS` | SDK/`HttpOptions` timeout (ms) |
| Redis clients | `REDIS_SOCKET_TIMEOUT_SEC` (default 5s) | `socket_timeout` + `socket_connect_timeout` (embedding cache uses `EMBEDDING_CACHE_REDIS_TIMEOUT_SEC`) |
| SQLAlchemy pool | 30s checkout | `pool_timeout` on engine |
| Health checks | 10s (embed), 10s (LLM) | `asyncio.wait_for` around single-attempt probes |

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
| `GET /documents` | 120/minute |
| `GET /documents/{id}/status` | 120/minute |
| `DELETE /documents/{id}` | 60/hour |
| `POST /feedback`, `GET /feedback` | 60/minute |

All limits are configurable via env vars (`RATE_LIMIT_*`).
429 responses return `{"detail": {"code": "rate_limited", "message": "..."}}`.
Rate-limit events are logged with tenant ID and path — raw API keys are never logged.

Storage uses Redis when `REDIS_URL` is configured, so **HTTP** rate limits
are shared across API replicas. SlowAPI `in_memory_fallback_enabled=True`
provides degraded **per-process** limiting if the Redis rate-limit store is
temporarily unreachable; ingestion still requires Redis via RQ.

These limiters are **not** Redis-backed and remain process-local (each replica
enforces its own cap):

| Limiter | Setting | Scope |
| --- | --- | --- |
| Embedding token bucket | `QUEUE_EMBEDDING_RPS` | Per API process, across that process's queue workers |
| Retrieval semaphore | `RETRIEVAL_MAX_CONCURRENCY` | Per API process |
| Batch LLM semaphore | `CHAT_BATCH_LLM_CONCURRENCY` | Per API process |
| SQLAlchemy retrieval semaphore | `SQLALCHEMY_RETRIEVAL_CONCURRENCY` | Per API process |

---

## Horizontal API Scaling

Multiple API containers are supported when `MULTI_API_INSTANCE=true`. That flag
enforces the requirements below at startup.

**Required**

| Requirement | Why |
| --- | --- |
| `QUEUE_BACKEND=redis` | Shared job queue and the stale-reconciler Redis lock |
| `ARTIFACT_STORAGE=s3` | Split API/worker hosts cannot see `QUEUE_SPILL_DIR` |
| `TENANT_REGISTRY_DISABLED=true` (default when `MULTI_API_INSTANCE=true`) | Tenant document lists are DB-authoritative; the in-memory registry is process-local |
| Redis lock around `fail_stale_documents_global` | Two replicas starting together must not fail a document another replica has already started |

**Distributed vs process-local**

| Mechanism | Distributed? |
| --- | --- |
| HTTP rate limits (`slowapi` + `REDIS_URL`) | Yes |
| Ingestion queue jobs (Redis/RQ) | Yes |
| Idempotency keys | Yes |
| Embedding cache (when enabled) | Yes |
| Stale-document reconciler lock | Yes (single winner) |
| Embedding / process token bucket (`QUEUE_EMBEDDING_RPS`) | No — per-instance cap |
| Retrieval / batch-LLM / SQLAlchemy semaphores | No — per-instance cap |
| Tenant registry cache | No — disabled by default in multi-instance |

Do not use Redis pub/sub to replicate the tenant registry. Kubernetes operators
and multi-region failover are out of scope.

Each replica still runs `uvicorn --workers 1`. Scale **containers**, not Uvicorn
worker processes.

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

**Auth non-goals:** ChatVector does not provide user login/signup, OAuth, RBAC, billing, or an API-key management UI. Keys are managed via CLI (`create-tenant-key`, `list-tenant-keys`, `revoke-tenant-key`, `rotate-tenant-key`, `set-tenant-key-expiry`, `set-tenant-key-external-user-id`) or direct DB updates.

**Session persistence:** All session state is now fully durable. Chat message turns are stored in `chat_messages`. Session metadata (`id`, `tenant_id`, `created_at`, `last_active`) is stored in the `sessions` table and document bindings are stored in `session_documents` — both introduced by migration `007_sessions.sql`. `backend/services/session_service.py` reads and writes exclusively through `SQLAlchemyService`; the previous in-memory `_SESSIONS` dict has been removed. Sessions survive backend restarts. The production Compose stack runs a single Uvicorn worker process per API container (`--workers 1`).

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
- Markdown (`.md`, `text/markdown` / `text/x-markdown`) requires a matching
  extension and UTF-8 or cp1254 encoding; embedded HTML is reduced to visible
  text (no script execution); link targets are not fetched (`[label](url)` →
  `label` in extracted text)
- HTML (`.html`/`.htm`, `text/html`) requires a matching extension and UTF-8 or
  cp1254 encoding (or a declared `<meta charset>`); visible text only —
  `script`/`style`/`noscript` bodies are dropped and remote resources are not
  fetched during extraction
- DOCX (`.docx`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`)
  requires a matching extension and ZIP/OOXML layout with `word/document.xml`;
  extraction uses safe ZIP/XML parsing with entry-count, uncompressed-size, and
  compression-ratio limits (configurable via `DOCX_MAX_*` env vars). Paragraphs,
  headings, and table cell text are extracted in document order; embedded media
  is omitted (no OCR). Encrypted packages are rejected with structured failure.

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

`GET /health` is a lightweight liveness probe for container orchestration
(no authentication, no upstream calls). Production Compose uses it for the
API healthcheck.

`GET /status` reports authenticated diagnostics for system components.
`metrics.documents_indexed` counts documents for the authenticated tenant only.
`metrics.document_queue` is an API-instance / shared-worker queue depth metric, not tenant-scoped.

| Component | Check | Cached |
| --- | --- | --- |
| API | Always online if responding | No |
| Database | Live `SELECT 1` + tenant-scoped document count | No |
| Embeddings | Single-attempt provider probe | Yes (TTL: `HEALTH_CHECK_CACHE_TTL_SECONDS`, default 60s) |
| LLM | Single-attempt provider probe | Yes (same TTL) |
| Redis | Ping (when `QUEUE_BACKEND=redis`) | Yes (same TTL) |

Provider health probes use at most **one upstream attempt** per cache refresh
(`retry_async` with `max_retries=0`) and short timeouts
(`EMBEDDING_HEALTH_CHECK_TIMEOUT_SEC` / `LLM_HEALTH_CHECK_TIMEOUT_SEC`, default 10s each).
Normal chat and embedding production paths retain the standard retry policy.

Health error responses expose stable codes only (`timeout`, `rate_limited`,
`api_key_missing`, `api_key_invalid`, `disconnected`, `error`) — never raw
exception text or URLs.

All checks run concurrently via `asyncio.gather`. Health checks never block
startup or crash the service.

The embedding and LLM checks are cached independently — a failing check is
still retried after TTL expires. Each result includes `cached` and
`checked_at` fields so operators can distinguish live vs cached results.

---

## Vector Search Design

**Retrieval pipeline (shipped):**

- **Scopes** — `session` (default: documents bound to the session) or `tenant` (all tenant documents)
- **Hybrid retrieval** — pgvector cosine similarity + PostgreSQL full-text search, merged via Reciprocal Rank Fusion (RRF); toggle with `HYBRID_RETRIEVAL_ENABLED`
- **Reranking** — deterministic similarity + lexical-overlap baseline reranker after fusion, or an optional hosted Cohere reranker (`RERANKER_PROVIDER=cohere`) with timeout, candidate cap, and fallback to retrieval order
- **Query transformations** — optional rewrite, expand, and stepback steps using session history context
- **Citation metadata** — each source includes collapsed `score` and `score_type` (`vector`, `hybrid_rrf`, or `reranked`), plus optional per-component fields when hybrid retrieval or reranking ran: `vector_score`, `full_text_score`, `rrf_score`, `reranker_score`, and `rerank_order`

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
- Session management (`create_session`, `list_sessions`, `delete_session`, `get_session_history`)
- Document management (`list_documents`, `delete_document`)
- Streaming chat (`stream_chat`) with typed `token` and `complete` events
- Sync ingestion SSE (`iter_document_status`) for document status streaming
- Async client (`AsyncChatVectorClient`) with the same surface as the sync client
- Retrieval scope options (`session` / `tenant`)
- Typed dataclass response models with citation `score` and `score_type`
- Retry with exponential backoff and jitter
- `Retry-After` header respected on 429 responses
- Typed exception hierarchy: `ChatVectorAuthError`, `ChatVectorRateLimitError`,
  `ChatVectorTimeoutError`, `ChatVectorAPIError`
- Context manager support

Async `iter_document_status`, component citation scores, upload metadata, `metadata_filter`, replacement, bulk upload, feedback, and idempotency keys are on both the Python and TypeScript clients. The TypeScript package is server-side only.

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
- **Knowledge graph / GraphRAG overlay (experimental)** — default off (`ENABLE_GRAPH_RETRIEVAL=false`); see [backend/rfcs/graph-retrieval.md](backend/rfcs/graph-retrieval.md)
- **Read replicas** — supported by existing DB abstraction layer

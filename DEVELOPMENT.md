# Development Guide

## Table of Contents

- [API Access](#api-access)
- [Quick Start](#quick-start)
- [Docker Reference](#docker-reference)
- [Database Initialization](#database-initialization)
- [Database migrations](#database-migrations)
- [Working with the Database Layer](#working-with-the-database-layer)
- [Ingestion Queue](#ingestion-queue)
- [Horizontal API scaling](#horizontal-api-scaling)
- [Tests](#tests)
- [Retry behavior](#retry-behavior)
- [Deployment](#deployment)
- [CI](#ci)
- [Frontend](#frontend)
- [Advanced Local Development](#advanced-local-development)
- [Git Workflow](#git-workflow)
- [Common Tasks](#common-tasks)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)

---

## API Access

Backend: http://localhost:8000
API Docs (Swagger UI): http://localhost:8000/docs _(disabled when `APP_ENV=production`)_
Database: PostgreSQL with pgvector (port 5432)

---

## Quick Start

For the full local environment (backend, frontend demo, provider setup), use the Makefile workflow documented in [README.md — Quick Start](README.md#-quick-start):

```bash
make quickstart
```

That runs guided provider configuration, installs frontend dependencies, builds the backend Docker image, starts services, and opens browser tabs when ready.

Returning contributors normally only need:

```bash
make
```

Backend-only (Docker stack):

```bash
docker compose up --build
```

Backend: http://localhost:8000  
Docs: http://localhost:8000/docs

---

## Docker Reference

```bash
# Rebuild backend after dependency changes
docker compose build api

# Start API + database
docker compose up api db

# Start database only
docker compose up db

# Stop containers
docker compose down

# Stop and remove data (WARNING: deletes DB data)
docker compose down -v

# View logs
docker compose logs -f api
docker compose logs -f db

# Check running services
docker compose ps

# Restart containers
docker compose restart

# Access PostgreSQL directly
docker compose exec db psql -U postgres -d postgres
```

### Makefile Commands

The project includes a `Makefile` with short commands for local development. Run `make help` for the full list.

```bash
make quickstart  # Configure provider, install/build, then start everything
make setup       # Configure env files, provider, dependencies, and Docker build
make             # Start backend + frontend, open browser tabs (default)
make dev         # Start backend + frontend without opening tabs
make backend     # Start only the backend Docker stack (attached logs)
make frontend    # Start only the frontend demo
make open        # Open frontend and API docs in your browser
make stop        # Stop this repo's frontend process and Docker services
make up          # Start containers (detached)
make build       # Rebuild and start containers
make down        # Stop containers
make reset       # Stop containers and remove volumes
make logs        # Follow API logs
make db          # Open Postgres shell
make tests       # Run tests via Docker (docker compose run --rm tests)
make prod-up     # Start production stack (standalone compose)
make prod-down   # Stop production stack
make prod-build  # Rebuild production stack
make clean       # Remove containers, volumes, and orphans
make cleanup     # Delete all local branches except main
make sync        # Sync fork with upstream main
make help        # Show all available commands
```

Press **Ctrl+C** during `make`, `make dev`, or `make quickstart` to stop the frontend; backend containers keep running until `make stop`.

Direct `docker compose` usage still works if preferred.

---

## Database Initialization

The database initializes automatically with:

- `pgvector` extension
- `documents` table
- `document_chunks` table
- Legacy SQL functions (`match_chunks`, `delete_document_atomic`) retained for
  existing databases — not called by current SQLAlchemy runtime code

Verify setup:

```bash
docker compose exec db psql -U postgres -d postgres

\dx
\dt

-- Optional: confirm legacy match_chunks RPC exists (not used by runtime)
SELECT proname FROM pg_proc WHERE proname = 'match_chunks';

\q
```

---

## Database migrations

Schema changes are **numbered SQL files** in `backend/db/init/`. The project does
not use Alembic or another migration framework — add a new file for each schema
change and apply it with `psql` (or let CI / Docker first-init apply the full
set automatically).

### Convention

| Rule | Detail |
| ---- | ------ |
| Location | `backend/db/init/` |
| Filename | `NNN_descriptive_name.sql` — three-digit prefix, then a short slug |
| Order | Lexical sort on the filename (`001` … `014` today; next is `015_*`) |
| Idempotency | Prefer `CREATE … IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, and guarded `DO …` blocks so re-runs are safe |
| ORM models | Update SQLAlchemy models in `backend/db/` to match new tables/columns |
| Ledger | Migrations after `008_schema_migrations.sql` must record their own filename as their final operation before `COMMIT` |

Current files (in apply order):

```
001_init.sql
002_dimensionless_vector.sql
003_atomic_delete.sql
004_chat_history.sql
004_hybrid_retrieval.sql   ← two files share prefix 004; order is alphabetical
005_api_keys.sql
006_tenant_fk_and_backfill.sql
007_sessions.sql
008_schema_migrations.sql
009_documents_tenant_id_not_null.sql
010_api_key_lifecycle.sql
011_document_chunks_unique_index.sql
012_documents_tenant_id_not_null_reconcile.sql
013_document_metadata.sql
014_document_replacement.sql
```

> **Do not add another `004_*` file.** Use the next unused number (`015_*` at
> time of writing). The duplicate `004` pair is historical; chat history always
> runs before hybrid retrieval because of alphabetical sort. Migration `008`
> baselines `004_hybrid_retrieval.sql` for databases created before the ledger;
> it does not re-apply hybrid DDL on every fresh install.

### How migrations are applied

**CI** (`.github/workflows/ci.yml`) — on every test job, all files are sorted
and executed in order:

```bash
for f in $(ls backend/db/init/*.sql | sort); do
  psql -v ON_ERROR_STOP=1 -f "$f"
done
```

**Docker first init** — `docker-compose.yml` and `docker-compose.prod.yml`
mount `backend/db/init/` into Postgres `docker-entrypoint-initdb.d`. Scripts
run **only when the data volume is empty** (first `docker compose up`). They do
not re-run on later restarts.

**Local Postgres** — apply the full set once after `createdb`, or apply a
single missing file when upgrading:

```bash
# Fresh local database
for f in $(ls backend/db/init/*.sql | sort); do
  psql -d chatvector_dev -v ON_ERROR_STOP=1 -f "$f"
done

# Single file (Docker path inside the development container)
docker compose exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/008_schema_migrations.sql'

# Single file (host path)
psql -d chatvector_dev -v ON_ERROR_STOP=1 \
  -f backend/db/init/008_schema_migrations.sql
```

### Adding a new migration (contributors)

1. Pick the next number — check `backend/db/init/`; use `015_*` if
   `014_document_replacement.sql` is the latest.
2. Add `backend/db/init/015_your_change.sql` with idempotent DDL (and any
   backfill `UPDATE`/`INSERT` the change needs) inside a transaction.
3. Make the idempotent ledger insert the final operation before `COMMIT`, so the
   schema changes and their ledger row become visible atomically:

   ```sql
   BEGIN;

   -- Idempotent schema/data changes go here.

   INSERT INTO public.schema_migrations (filename)
   VALUES ('009_your_change.sql')
   ON CONFLICT (filename) DO NOTHING;

   COMMIT;
   ```

4. Update SQLAlchemy models and services if the runtime code depends on the new
   schema.
5. Add or update tests that exercise the new schema path and ledger record.
6. In the PR description, note whether operators with **existing** databases must
   apply the file manually (see below).

CI will apply your file automatically; reviewers can verify ordering and
idempotency from the filename and SQL.

### Upgrading an existing database

Postgres init scripts do **not** run again on a volume that already has data.
After pulling a release that adds a migration, inspect the ledger and apply only
files that are genuinely missing. The startup check detects drift but never runs
SQL or applies migrations automatically.

The Docker commands below expand `POSTGRES_USER` and `POSTGRES_DB` inside the
database container, so they target the database configured for that Compose
stack rather than assuming the development defaults.

Inspect the ledger:

```bash
# Development stack
docker compose exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT filename, applied_at FROM public.schema_migrations ORDER BY filename;"'

# Production stack
docker compose -f docker-compose.prod.yml exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT filename, applied_at FROM public.schema_migrations ORDER BY filename;"'
```

If this reports that `public.schema_migrations` does not exist, follow the
pre-ledger baseline procedure below.

Apply each verified missing file separately, in lexical order, and stop on the
first SQL error:

```bash
# Development stack (Docker path inside the database container)
docker compose exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/009_your_change.sql'

# Production stack
docker compose -f docker-compose.prod.yml exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/009_your_change.sql'

# Or a host path with local psql
psql -d chatvector_dev -v ON_ERROR_STOP=1 \
  -f backend/db/init/009_your_change.sql
```

Do **not** run every migration over a populated database: `001_init.sql` drops
and recreates core tables. The full sorted loop is only for a newly created,
empty database.

For a database created before the ledger existed, `008_schema_migrations.sql`
is a baseline bridge. It assumes that `001_init.sql` through `007_sessions.sql`
were already applied; it does not inspect the old schema to prove that history.
Verify the schema or deployment history, apply any genuinely missing historical
files individually in lexical order, and then apply `008_schema_migrations.sql`.

```bash
# Development stack
docker compose exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/008_schema_migrations.sql'

# Production stack
docker compose -f docker-compose.prod.yml exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/008_schema_migrations.sql'
```

Its backfill is idempotent. The `applied_at` values it creates for migrations
`001` through `008` record when the baseline backfill ran, not when each older
migration originally ran.

If the ledger table exists but a row for `001` through `007` is missing, that
missing row alone does **not** prove the historical SQL is unapplied. Verify the
migration's schema effects or deployment history, apply only genuinely missing
historical SQL, and then rerun `008_schema_migrations.sql` to restore all baseline
rows idempotently. For a missing migration after `008`, apply that migration file
itself; later files record their own ledger rows.

**Dev wipe** (simplest when data loss is acceptable):

```bash
docker compose down -v
docker compose up --build
```

Feature-specific upgrade notes (dimensionless vectors, API keys, hybrid
retrieval, sessions) live under [Deployment](#deployment). They reference the
same files; prefer this section for the general workflow.

### Migration ledger and startup drift check

Migration `008_schema_migrations.sql` creates the runtime ledger and backfills
one row for every migration from `001_init.sql` through itself:

```sql
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  filename TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

The backfill uses `ON CONFLICT (filename) DO NOTHING`, so re-running `008` does
not create duplicate-key failures. Each later migration records its own filename
as its final operation before `COMMIT` using the same conflict handling.

If migrations run as a different PostgreSQL role than the application, grant the
runtime role read access to the ledger after applying `008`:

```sql
GRANT SELECT ON public.schema_migrations TO chatvector_app;
```

Replace `chatvector_app` with the role used by `DATABASE_URL`.

At application startup, ChatVector compares the lexically sorted
`backend/db/init/*.sql` filenames with the ledger:

- A missing `schema_migrations` table stops startup with instructions to apply
  the historical migrations and `008_schema_migrations.sql`.
- A ledger relation with the wrong columns, types, primary key, nullability, or
  timestamp default stops startup as malformed instead of being treated as current.
- Any migration file without a matching ledger row stops startup and lists the
  missing filename(s).
- Ledger rows that have no matching file in the running checkout produce a
  warning, because the database may be newer than the application; startup
  continues when that is the only difference.

This check is detection only. It does not execute migrations, modify the ledger,
or replace the operator-run `psql -v ON_ERROR_STOP=1 -f ...` workflow.

If startup reports a malformed ledger, inspect it before changing anything:

```bash
docker compose exec db sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "\d+ public.schema_migrations"'
```

Back up and verify existing ledger rows, repair the relation to the documented
two-column contract, and rerun `008_schema_migrations.sql`. Do not drop or replace
the ledger blindly on a populated database.

---

## Working with the Database Layer

All database access must go through the service abstraction layer.

### 1. Add method to base class (`db/base.py`)

```python
from abc import abstractmethod

@abstractmethod
async def new_operation(self, param: str) -> str:
    pass
```

### 2. Implement in the service

- `db/sqlalchemy_service.py` (all environments)

### 3. Use via factory

```python
import db

result = await db.new_operation("test")
```

The factory always returns `SQLAlchemyService`, applies
retry logic with timeouts and jitter, and handles logging.

See [ARCHITECTURE.md](ARCHITECTURE.md) for full details on the
database strategy pattern and retry behavior.

---

## Ingestion Queue

`POST /upload` returns immediately with a `document_id` and
`status_endpoint`. Processing happens in the background via an async
worker pool. Poll `GET /documents/{id}/status` for progress, or list tenant
documents with `GET /documents`.

**Status flow:**

```
queued → extracting → chunking → embedding → storing → completed
                                                      ↘ failed
```
### Status updates: poll vs stream

There are two ways to track ingestion progress after upload:

**List:** `GET /documents`
Returns `{ tenant_id, documents: [{ document_id, file_name, status, created_at, updated_at }] }`
for the authenticated tenant. Used by the batch demo to populate the document picker.

**Poll:** `GET /documents/{document_id}/status`
Standard JSON response. Works with any HTTP client and is the recommended
fallback for simple integrations.

**Stream:** `GET /documents/{document_id}/status/stream`
Server-Sent Events (SSE). Requires `ENABLE_STREAMING=true` in
`backend/.env` (see `backend/.env.example`). The event name is `status`;
the payload shape matches the poll endpoint — same `status`, `chunks`,
`error`, `timestamps`, and `queue_position` (when queued) fields.

**Frontend demo behavior:** the demo client (`frontend-demo/app/lib/hooks/useDocumentPolling.ts`)
tries the SSE stream first and falls back to polling automatically if the
stream fails or streaming is disabled.

> **Note:** The stream endpoint works by polling the database on a ~1 second
> interval and emitting SSE events — it is not a push-from-worker channel yet.

### Chat streaming (`POST /chat/stream`)

Requires `ENABLE_STREAMING=true` in `backend/.env`. The request body matches
`POST /chat`.

**SSE events:**

| Event | Payload | Notes |
|---|---|---|
| `token` | JSON string | Incremental answer text. Format unchanged for existing clients. |
| `complete` | JSON object | Final metadata: `type`, `session_id`, `sources`, `latency_ms`, `request_latency_ms`, `model`. |
| `done` | `[DONE]` | **Deprecated.** Retained for backward compatibility; emitted after `complete`. |
| `error` | JSON object | `type`, `code`, and `message`. Valid JSON — not a plain string. |

Example successful sequence:

```text
event: token
data: "Hello"

event: complete
data: {"type":"complete","session_id":"...","sources":[...],"latency_ms":1234,"request_latency_ms":1500,"model":"..."}

event: done
data: [DONE]
```

Example error:

```text
event: error
data: {"type":"error","code":"llm_rate_limited","message":"..."}
```

**Interruption behavior:** client disconnects, generator cancellation, and
provider failures mid-stream stop the stream without persisting a partial
assistant message. User and assistant messages are stored only after a
successful `complete` event.

**Latency note:** `latency_ms` in the `complete` event measures LLM generation
wall time for the stream, not retrieval or embedding time.
`request_latency_ms` is the additive total from stream start through `complete`,
including history resolution, query transformation, embedding, and retrieval.

### Citation score types

Chat and batch responses include citation metadata on each `sources[]` item:

| Field | Description |
|---|---|
| `score` | Numeric relevance value from the final ranking stage (unchanged). |
| `score_type` | Label describing what `score` means. |

Supported `score_type` values:

| Value | Meaning | Higher is better? | Typical range |
|---|---|---|---|
| `vector` | Cosine similarity from pgvector (`1 - distance`) | Yes | Roughly `0.0`–`1.0` for normalized embeddings |
| `hybrid_rrf` | Reciprocal Rank Fusion score combining vector + keyword ranks | Yes | Small positive values (rank-based, not a probability) |
| `reranked` | Combined retrieval + lexical overlap score from the reranker | Yes | Roughly `0.0`–`1.0` depending on upstream scores |

**Important:** scores from different `score_type` values are **not directly comparable**.
A `vector` score of `0.82` and a `hybrid_rrf` score of `0.03` do not indicate
equivalent relevance. Compare scores only within the same `score_type`.

When reranking is enabled (`ENABLE_RERANKING=true`), final citations use
`score_type: "reranked"`. When hybrid retrieval is active, citations use
`hybrid_rrf` unless reranking runs afterward.

##### Hosted reranker (Cohere)

`RERANKER_PROVIDER=cohere` (or a per-request `reranker_provider: "cohere"` together
with `reranking_enabled: true`) sends the retrieved chunks to the Cohere rerank API.
`ENABLE_RERANKING` stays `false` by default; a request can turn reranking on for
itself without changing the process setting. The interface (`RerankerProvider`)
allows a second hosted vendor later.

| Env var | Default | Purpose |
|---|---|---|
| `COHERE_API_KEY` | unset | Vendor key. Process env only; request bodies cannot supply it. |
| `COHERE_RERANK_MODEL` | `rerank-v3.5` | Cohere rerank model. |
| `COHERE_RERANK_URL` | `https://api.cohere.com/v2/rerank` | Rerank endpoint. |
| `RERANKER_TIMEOUT_SEC` | `5` | Hard overall timeout per vendor call. |
| `RERANKER_MAX_CANDIDATES` | `50` | Max chunks sent per request; extra candidates keep retrieval order after the reranked ones. |

If the vendor times out, returns an error, returns an invalid body, or the key is
missing, chat still returns `200` using the pre-rerank retrieval order (truncated to
`match_count`). The reason is logged and, with `debug_retrieval=true`, reported as
`retrieval_debug.reranker.fallback_reason`.

#### Component score fields (retrieval inspector)

Each `sources[]` item may also include optional component scores when the
corresponding retrieval stage ran. These fields are additive — existing
clients can ignore them. The top-level `score` and `score_type` fields are
unchanged.

| Field | Description | Present when |
|---|---|---|
| `vector_score` | Cosine similarity from pgvector (`1 - distance`) | Vector search ran for this chunk |
| `full_text_score` | PostgreSQL `ts_rank` from keyword search | Hybrid retrieval ran and the chunk matched keyword search |
| `rrf_score` | Reciprocal Rank Fusion score | Hybrid retrieval merged vector + keyword ranks |
| `reranker_score` | Combined retrieval + lexical overlap score | Reranking ran (`ENABLE_RERANKING=true`) |
| `rerank_order` | 1-based position after reranking | Reranking ran |

Component fields are omitted when the corresponding stage did not run or did
not produce a value for that chunk. Compare component scores only within the
same field — they are not interchangeable across fields or with `score`.

---

```env
QUEUE_WORKER_COUNT=3      # concurrent background workers (1–5)
QUEUE_MAX_SIZE=100        # max pending jobs; uploads beyond this return 503
QUEUE_EMBEDDING_RPS=2.0   # max embedding HTTP batches/sec per API process (burst = same value)
QUEUE_SPILL_DIR=/tmp/chatvector  # local ArtifactStorage root for Redis uploads
ARTIFACT_STORAGE=local           # local (default) or s3 for split API/worker hosts
ARTIFACT_TTL_SECONDS=86400       # S3 expiry mark; artifacts are also deleted after terminal ingest
# ARTIFACT_S3_BUCKET=            # required when ARTIFACT_STORAGE=s3
# ARTIFACT_S3_ENDPOINT_URL=      # MinIO or other S3-compatible endpoint
# ARTIFACT_S3_ACCESS_KEY=        # or AWS_ACCESS_KEY_ID
# ARTIFACT_S3_SECRET_KEY=        # or AWS_SECRET_ACCESS_KEY
QUEUE_DLQ_MAX_ENTRIES=1000  # max dead-letter records retained
QUEUE_JOB_MAX_RETRIES=3   # retries before a job moves to DLQ
QUEUE_RETRY_BASE_DELAY=2.0 # base seconds for retry backoff
```

Inspect the dead-letter queue at any time:

```bash
curl http://localhost:8000/queue/stats
```

> **Note:** The default queue is in-memory for local development. In production
> (`APP_ENV=production`), the Redis-backed queue is the default. Set
> `QUEUE_BACKEND=redis` explicitly in development to test Redis locally.

See [ARCHITECTURE.md](ARCHITECTURE.md) for full queue and pipeline details.

### Ingestion completion webhooks (v1)

Optional signed HTTP callbacks when ingestion reaches a terminal state. All
configuration is environment-only (`WEBHOOK_ENABLED`, `WEBHOOK_URL`,
`WEBHOOK_SECRET`, `WEBHOOK_MAX_ATTEMPTS`, `WEBHOOK_TIMEOUT_SECONDS` — see
`backend/.env.example`).

- Event types: `ingestion.completed`, `ingestion.failed`
- Payload includes `event_id`, `document_id`, `tenant_id`, `status`, `timestamps`,
  and `error_summary` on failures
- Header `X-ChatVector-Signature`: `sha256=<hex>` HMAC-SHA256 of the raw JSON body
  (sorted keys, compact separators) using `WEBHOOK_SECRET`
- Delivery uses RQ queue `chatvector-webhooks` with the payload in job args (no spill
  files). Retries are bounded by `WEBHOOK_MAX_ATTEMPTS`.
- Consumers should dedupe on `event_id` (at-least-once delivery).

**Signature test vector** (also asserted in `test_ingestion_webhook.py`):

```
Secret: test_webhook_secret
Body (exact bytes):
{"document_id":"doc-123","event_id":"550e8400-e29b-41d4-a716-446655440000","event_type":"ingestion.completed","status":"completed","tenant_id":"tenant-a","timestamps":{"completed_at":"2026-01-15T12:00:00Z","enqueued_at":"2026-01-15T11:59:50Z","started_at":"2026-01-15T11:59:55Z"}}

Expected X-ChatVector-Signature:
sha256=dd436d2019c2026e493fa1886dd1cb97e46df8e7fe6e343cf8bf59ed14903dcf
```

When `WEBHOOK_ENABLED=false`, the ingestion pipeline does not enqueue or deliver
webhooks.

---

## Retrieval evaluation

`python -m backend.cli eval` measures retrieval quality against a JSON fixture. It calls `retrieve_for_documents`, the same boundary chat uses. It does not call the answer-generation LLM. The embedding cache stays off unless you pass `--allow-cache`.

```bash
python -m backend.cli eval \
  --dataset path/to/queries.json \
  --tenant-id your-tenant \
  --k 5,10 \
  --match-count 10 \
  --export /tmp/eval.json
```

Repeat `--config path/to/arm.json` to compare retrieval settings. Omit `--config` to score the current process defaults. Metrics are recall@k, MRR, and nDCG@k, plus retrieval latency. `--export` writes the config snapshot and per-query results.

Each query needs `relevant_chunks` (`[document_id, chunk_index]`) and/or `relevant_doc_ids`. `doc_ids` are the documents to search. `simulate_session` defaults to false, so a run does not inherit conversational history unless the fixture sets it.

An arm file is a JSON object of retrieval overrides, for example `{"hybrid_enabled": true, "match_count": 8}`. There is no public HTTP retrieval endpoint.

---

## Horizontal API scaling

Each API container still runs `uvicorn --workers 1`. To run more than one
container, set:

```env
MULTI_API_INSTANCE=true
QUEUE_BACKEND=redis
ARTIFACT_STORAGE=s3
ARTIFACT_S3_BUCKET=your-bucket
```

`MULTI_API_INSTANCE=true` defaults `TENANT_REGISTRY_DISABLED=true` (DB-authoritative
tenant document lists) and requires Redis plus S3 artifacts. Startup reconciliation
uses a Redis lock so two replicas cannot double-fail the same in-flight document.

Process-local semaphores (`RETRIEVAL_MAX_CONCURRENCY`,
`CHAT_BATCH_LLM_CONCURRENCY`, `SQLALCHEMY_RETRIEVAL_CONCURRENCY`) and
`QUEUE_EMBEDDING_RPS` are **per-instance caps**. HTTP rate limits are Redis-backed
via slowapi.

### Topology smoke procedure

Automated (required — lock behavior is asserted in tests, not docs-only):

```bash
pytest backend/tests/test_stale_reconciliation.py backend/tests/test_tenant_registry.py -v --tb=short
```

Manual two-replica checklist: see [DEPLOYMENT.md](DEPLOYMENT.md#horizontal-api-topology-smoke).
Start a second API process on another host port with the same Redis/Postgres/S3
settings — do not `--scale api=2` against the published `8000:8000` mapping.

---

## Tests

This project uses `pytest` and `pytest-asyncio`.

### Using Docker (Recommended)

```bash
make tests
# or
docker compose run --rm tests
```

### Running Locally

`backend/requirements.txt` installs `psycopg[binary]`, which bundles
the Postgres client library for most platforms. On Python 3.13 or
non-standard environments `psycopg_binary` may not be available; if you
see `libpq library not found` errors, run tests via Docker instead
(`make tests`) or install `libpq` and `psycopg[c]` manually.

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

Tests that open real PostgreSQL connections still need a running
Postgres instance — use `docker compose up -d db` first.

Common options:

```bash
pytest -v         # verbose
pytest -x         # stop on first failure
pytest -s         # show print statements
pytest -k "chat"  # run tests matching pattern
```

---

## Retry behavior

ChatVector uses a shared retry contract across the backend, provider layer, and
official SDKs. The goal is consistent handling of transient failures (429, 502,
503, 504, 408, timeouts, and connection errors) without replaying ambiguous
mutating HTTP requests.

### Semantics

| Setting | Backend (`utils/retry.py`) | Python SDK | TypeScript SDK |
| --- | --- | --- | --- |
| `max_retries` meaning | Retries **after** the first attempt | Same | `maxRetries` — same |
| Default max retries | 3 (4 total attempts) | 2 (3 total attempts) | 2 (3 total attempts) |
| Base delay | 1.0s | 0.5s | 500ms |
| Backoff multiplier | 2.0 | 2.0 | 2× per retry index |
| Jitter | Full jitter: `uniform(0, cap)` | Full jitter with 8s cap | Full jitter with 8s cap |
| `Retry-After` | Not parsed at backend layer | Numeric delta-seconds only (floors sleep via `WantsRetry`); HTTP-date values ignored | Parses delta-seconds and HTTP-date via `parseRetryAfter` |
| Per-attempt timeout | Yes (`asyncio.wait_for`; DB deadline = `SQLALCHEMY_STATEMENT_TIMEOUT_SEC + 5`) | httpx client timeout (30s default) | Per-request timeout (30s default) |

### Retryable errors

**Backend** (`is_transient_error` in `backend/utils/retry.py`):

- `asyncio.TimeoutError`
- `ProviderRateLimitError`, `ProviderTimeoutError`, `ProviderConnectionError`
- SQLAlchemy `IntegrityError`, `DataError`, and `ProgrammingError` are **never** transient (even when bound parameters contain words like "timeout")
- Other DB/driver errors: message patterns on the underlying driver/original exception only
- Generic `ProviderError` and `ProviderAuthError` fail fast (message substrings are not used)
- Ollama/Voyage map HTTP `408`, `429`, `502`, `503`, `504` to the structured transient types above (`500` is not retried)

**HTTP status codes** (SDK clients and documentation): `408`, `429`, `502`, `503`, `504` (not `500`)

### Where retries apply

| Surface | Retries? | Notes |
| --- | --- | --- |
| DB factory (`db/__init__.py`) | Yes | Most ops; non-idempotent writes use `retry_on_timeout=False` |
| DB writes (`create_document`, chunk storage, atomic upload) | Connection/transient only | No retry after ambiguous client timeout |
| Session reads/deletes/bindings | Yes | `list_session_records`, `get_session_record`, etc. |
| `store_chat_message` / `store_chat_turn` / `create_session_record` | No | Not idempotent under timeout retry |
| `list_applied_migrations` | No | Startup has its own bounded retry loop |
| Embedding service | Yes | Wraps provider `embed()`; OpenAI/Anthropic SDK retries disabled (`max_retries=0`) |
| LLM answer generation (non-streaming) | Yes | Wraps provider `generate()`; streaming is not retried |
| LLM streaming | No | Bytes may have started — explicit non-goal |
| Query transformation | No | Soft-fails without backend retry |
| HTTP middleware (`POST /chat`, upload) | No | Explicit non-goal |
| Ingestion queue job failures | Selective | Retries only when `is_transient_error()`; auth/parse/programming errors → DLQ |
| Python/TS SDK `GET`/`HEAD` | Yes | Safe, idempotent reads |
| Python/TS SDK mutating methods | No | Upload, chat, sessions, streaming |

**Batch LLM concurrency:** `CHAT_BATCH_LLM_CONCURRENCY` (default `4`) limits the maximum
concurrent batch `transform_query` and `generate_answer` LLM work **per API process**
(module-level shared semaphore). Two simultaneous `POST /chat/batch` requests in the
same process still share that cap — e.g. with value `4`, at most four transform/answer
operations run concurrently across all in-flight batch work in that process.
It does not apply to shared embedding, retrieval, or non-batch chat paths.

**Single-document batch items** are compare-style. Three history uses stay separate:

- **Generation history injection** — session history is not added to the LLM context.
- **Chat turn persistence** — a successful turn is not stored, even when `session_id` is set.
- **Transform / standalone resolution** — session history is not passed into
  `transform_query` unless the item sets `skip_history_transform` to false.

`/chat` and `/chat/stream` use session history for gated retrieval resolution
and for generation. With `HISTORY_AWARE_RETRIEVAL_DEFAULT=true`, an extra
resolution LLM call is made only when the need-resolution gate says the
follow-up depends on prior turns — not on every session turn. Rewrite,
expand, and step-back stay off unless query transformation is enabled.
`HISTORY_AWARE_RETRIEVAL_DEFAULT=false` restores the older rule: resolution
runs only when `QUERY_TRANSFORMATION_ENABLED=true`, and then on every
non-empty history window. History-Aware Follow-Up Query Transformation
Traces covers the debug field names. This split is only the compare-style
batch rule.

### Audit checklist

- [x] `embedding_service.py` — `retry_async` with shared defaults
- [x] `answer_service.py` — non-streaming `generate_answer` uses `retry_async`
- [x] `answer_service.py` — streaming path intentionally has no retry
- [x] Provider clients — map rate limits/timeouts/connections to shared exception types
- [x] `db/__init__.py` — retry at factory layer (status-update ops use shorter base delay)
- [x] Python SDK — GET/HEAD only, full jitter, `Retry-After` floor
- [x] TypeScript SDK — GET/HEAD only (existing behavior documented in `sdk/typescript/README.md`)

---

## Deployment

For production setup (environment variables, pgvector, Redis, API-key bootstrap,
Docker Compose, and common pitfalls), see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

### Local development

For day-to-day work use the [Quick Start](#quick-start) flow
(`make quickstart`, `make`, or `docker compose up --build`). That stack
mounts live backend code and uses development defaults.

### Local production simulation

`docker-compose.prod.yml` is a **standalone** file — it does not
extend or merge with `docker-compose.yml`. It disables code bind
mounts, runs single-process uvicorn (`--workers 1`), enables JSON logging, and applies
resource limits.

```bash
# Copy and configure production env
cp backend/.env.example backend/.env.prod
# Edit .env.prod with real values

# Start production stack (make prod-up uses backend/.env.prod)
make prod-up
# or
docker compose -f docker-compose.prod.yml --env-file backend/.env.prod up -d
```

`make prod-up`, `make prod-down`, and `make prod-build` pass
`--env-file backend/.env.prod`. Application logs are written to
`logs/app.log` **and** stdout (JSON when `LOG_FORMAT=JSON`).

### Production Docker Compose E2E smoke test

The production Compose E2E smoke test verifies the complete production-style
Docker Compose stack from startup through authenticated document processing and
chat.

The test is implemented in:

```text
scripts/prod-e2e-smoke.sh
```

The smoke test covers the following flow:

1. Builds and starts the production Docker Compose stack.
2. Waits for the API health endpoint to become available.
3. Creates a temporary tenant and production API key.
4. Creates a document fixture.
5. Uploads the document using Bearer API-key authentication.
6. Polls the document status endpoint until ingestion completes.
7. Verifies that document ingestion completed successfully.
8. Sends an authenticated chat request using the uploaded document.
9. Validates that the chat response:
   - is a valid JSON object,
   - has `status: "ok"`,
   - contains a non-empty answer,
   - contains at least one source.
10. Cleans up the production Compose containers, volumes, network, and orphan
    containers when the test exits.

Run the smoke test locally with:

```bash
./scripts/prod-e2e-smoke.sh
```

The script automatically starts the production stack using:

```text
docker-compose.prod.yml
```

The production Compose stack requires the following environment variables:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=postgres
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/postgres
REDIS_URL=redis://redis:6379/0
APP_ENV=production
LLM_PROVIDER=...
LLM_MODEL=...
EMBEDDING_PROVIDER=...
EMBEDDING_MODEL=...
GEN_AI_KEY=...
QUEUE_BACKEND=redis
QUEUE_WORKER_COUNT=3
LOG_LEVEL=INFO
```

For CI, these values are supplied by GitHub Actions. LLM and embedding
configuration is read from repository variables, while `GEN_AI_KEY` is
provided through GitHub Actions secrets.

The CI job is defined in:

```text
.github/workflows/ci.yml
```

The CI smoke-test step runs:

```yaml
- name: Run production Compose E2E smoke test
  env:
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres
    POSTGRES_DB: postgres
    DATABASE_URL: postgresql+asyncpg://postgres:postgres@db:5432/postgres
    REDIS_URL: redis://redis:6379/0
    APP_ENV: production
    LLM_PROVIDER: ${{ vars.CI_LLM_PROVIDER }}
    LLM_MODEL: ${{ vars.CI_LLM_MODEL }}
    EMBEDDING_PROVIDER: ${{ vars.CI_EMBEDDING_PROVIDER }}
    EMBEDDING_MODEL: ${{ vars.CI_EMBEDDING_MODEL }}
    GEN_AI_KEY: ${{ secrets.GEN_AI_KEY }}
    QUEUE_BACKEND: redis
    QUEUE_WORKER_COUNT: 3
    LOG_LEVEL: INFO
  run: |
    chmod +x scripts/prod-e2e-smoke.sh
    ./scripts/prod-e2e-smoke.sh
```

If the smoke test fails in CI, the workflow prints the production Compose
service status and container logs to help diagnose API, database, Redis,
configuration, or ingestion failures.

The CI workflow also performs cleanup after the test:

```bash
docker compose -f docker-compose.prod.yml down -v --remove-orphans
```

### Production API health endpoint

The production Compose API healthcheck uses:

```text
GET /health
```

The endpoint returns:

```json
{
  "status": "ok"
}
```

The endpoint is intentionally lightweight and is used to determine whether the
API process is ready to accept HTTP requests.

It is excluded from the OpenAPI schema:

```python
@router.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
```

The production Compose healthcheck uses this endpoint:

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

The smoke-test script also waits for this endpoint before creating the tenant
and API key or uploading the fixture.

### Production Compose configuration

The production Compose API explicitly receives the LLM, embedding, and Redis
queue configuration:

```yaml
environment:
  DATABASE_URL: ${DATABASE_URL}
  APP_ENV: production

  GEN_AI_KEY: ${GEN_AI_KEY}

  LLM_PROVIDER: ${LLM_PROVIDER}
  LLM_MODEL: ${LLM_MODEL}

  EMBEDDING_PROVIDER: ${EMBEDDING_PROVIDER}
  EMBEDDING_MODEL: ${EMBEDDING_MODEL}

  QUEUE_BACKEND: ${QUEUE_BACKEND:-redis}
  QUEUE_WORKER_COUNT: ${QUEUE_WORKER_COUNT:-3}

  LOG_FORMAT: JSON
  LOG_LEVEL: ${LOG_LEVEL:-INFO}
  CORS_ORIGINS: ${CORS_ORIGINS}
  REDIS_URL: ${REDIS_URL:-redis://redis:6379/0}
  PYTHONPATH: /app
```

The production API runs with a single Uvicorn worker process **per container**:

```yaml
command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

RQ worker threads (`QUEUE_WORKER_COUNT`) provide ingestion concurrency within
that API process. Scale **containers** with `MULTI_API_INSTANCE=true` (see
[Horizontal API scaling](#horizontal-api-scaling)); do not raise `--workers`.

The API container has a 1 GB memory limit:

```yaml
deploy:
  resources:
    limits:
      memory: 1g
```

The production stack uses Redis for the ingestion queue:

```env
QUEUE_BACKEND=redis
QUEUE_WORKER_COUNT=3
```

This allows the E2E test to verify the production-style path across the API,
PostgreSQL, Redis-backed ingestion, document processing, authentication, and
authenticated chat.

### Smoke-test success criteria

A successful run ends with:

```text
=========================================
Production E2E smoke test PASSED
=========================================
```

The test is considered successful only when:

- the production Compose stack starts successfully;
- the API becomes healthy;
- a tenant and API key can be created;
- a document can be uploaded using authenticated access;
- document ingestion reaches `completed`;
- the completed document contains processed chunks;
- an authenticated chat request succeeds;
- the response contains a non-empty answer;
- the response contains at least one source.

The smoke test is intended as a production-style integration check rather than
a load test. It validates that the major components work together through the
real HTTP API and production Compose configuration.

### Production environment variables

| Variable              | Required     | Notes                                                           |
| --------------------- | ------------ | --------------------------------------------------------------- |
| `GEN_AI_KEY`          | **Required** | Google AI Studio / Gemini API key                               |
| `DATABASE_URL`        | **Required** | `postgresql+asyncpg://…` pointing at PostgreSQL with pgvector enabled |
| `APP_ENV=production`  | **Required** | Disables `/docs`, enforces Bearer API-key auth, Redis queue default |
| `CORS_ORIGINS`        | **Required** | Comma-separated list of allowed browser origins                 |
| `POSTGRES_USER`       | **Required** | Used by `db` service in `docker-compose.prod.yml`               |
| `POSTGRES_PASSWORD`   | **Required** | As above                                                        |
| `POSTGRES_DB`         | **Required** | As above                                                        |
| `LOG_LEVEL`           | Optional     | Default: `INFO`                                                 |
| `LOG_FORMAT`          | Optional     | `TEXT` or `JSON` (default: `TEXT`; use `JSON` for log shipping) |
| `MAX_CONTEXT_CHARS`   | Optional     | Max chars of retrieved context sent to LLM; default `32000`     |
| `QUEUE_WORKER_COUNT`  | Optional     | Default: `3`                                                    |
| `QUEUE_EMBEDDING_RPS` | Optional     | Default: `2.0`                                                  |
| `LLM_HTTP_TIMEOUT_MS` | Optional     | Default: `60000`                                                |
| `CHUNKING_STRATEGY`   | Optional     | `fixed` (default), `paragraph`, or `semantic`                   |

See `backend/.env.example` for the full list of tunables.

### Upgrading from a pre-#167 Deployment

See [Database migrations](#database-migrations) for the general upgrade workflow.
This release predates the dimensionless-vector change.

Versions before PR #167 created `document_chunks.embedding` as `vector(3072)`.
The current schema uses a dimensionless `vector` column to support multiple
embedding providers.

**Option A — Run the migration (keeps existing data):**

```bash
docker compose exec db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/002_dimensionless_vector.sql
```

Or connect directly and paste the contents of
`backend/db/init/002_dimensionless_vector.sql`.

> **Note:** existing embeddings are preserved but become incompatible if you
> switch to a provider with a different embedding dimension. A full re-ingest
> is required after a provider change.

**Option B — Full wipe and re-ingest (simplest for dev environments):**

```bash
docker compose down -v
docker compose up --build
```

### API-key authentication and tenant isolation (`005` + `006`)

See [Database migrations](#database-migrations) for applying files on existing volumes.

Issue #335 adds multi-tenant API-key authentication. Fresh Docker installations apply
`005_api_keys.sql` and `006_tenant_fk_and_backfill.sql` automatically on first start.

**Upgrading an existing installation:**

```bash
# Apply the schema migrations
docker compose exec db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/005_api_keys.sql
docker compose exec db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/006_tenant_fk_and_backfill.sql
```

After applying `005`, any pre-existing documents have `tenant_id=NULL` and are not
accessible by any authenticated tenant until backfilled.

**Backfill pre-existing documents** (choose one option):

```sql
-- Option A: assign all unowned documents to a known tenant
UPDATE documents SET tenant_id = '<your-tenant-id>' WHERE tenant_id IS NULL;

-- Option B: delete orphaned documents (irreversible)
DELETE FROM documents WHERE tenant_id IS NULL;
```

After backfilling, apply `006` to add the foreign key from `documents.tenant_id → tenants.id`.
The FK is guarded by a `DO … IF NOT EXISTS` block so it is safe to re-run.

**Enforce NOT NULL on `documents.tenant_id` (`009`):**

Fresh Docker/CI installs apply `009_documents_tenant_id_not_null.sql` automatically after
backfill-safe checks pass. Existing installations with legacy `tenant_id IS NULL` rows
must backfill first (same options as above), then apply:

```bash
docker compose exec db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/009_documents_tenant_id_not_null.sql
```

If NULL rows remain, migration `009` logs a notice and skips the constraint so you can
backfill and re-run. Once enforced, deleting a tenant cascades to its documents
(`ON DELETE CASCADE` replaces the earlier `ON DELETE SET NULL` from `006`).

**Bootstrap a tenant and API key** (run once per environment):

```bash
cd backend
python -m backend.cli create-tenant-key --tenant "My Org" --tenant-id my-org
```

The raw API key (`cv_live_…`) is displayed **once** and is never stored.
Record it immediately. Use it as `Authorization: Bearer <raw-key>` in all requests.

**Managing keys after bootstrap:**

```bash
python -m backend.cli list-tenant-keys --tenant-id <id>
python -m backend.cli revoke-tenant-key --tenant-id <id> --key-id <key-id>
python -m backend.cli rotate-tenant-key --tenant-id <id> --key-id <key-id>
python -m backend.cli set-tenant-key-expiry --tenant-id <id> --key-id <key-id> --expires-at <iso>
python -m backend.cli set-tenant-key-expiry --tenant-id <id> --key-id <key-id> --expires-at clear
python -m backend.cli set-tenant-key-external-user-id --tenant-id <id> --key-id <key-id> --external-user-id <id>
python -m backend.cli set-tenant-key-external-user-id --tenant-id <id> --key-id <key-id> --external-user-id clear
```

Optional fields on create:

```bash
python -m backend.cli create-tenant-key --tenant "My Org" --tenant-id my-org \
  --external-user-id user-123 --expires-at 2026-12-31T23:59:59
```

`list-tenant-keys` shows `external_user_id` and `expires_at` metadata but never raw secrets.
Rotation prints a new raw key once (same security model as create).
Expired keys return HTTP 401 with code `expired_api_key`; revoked keys use `revoked_api_key`.

Revoking is idempotent — running it again on an already-revoked key won't error.

**Apply API key lifecycle columns (`010`):**

Existing installations need migration `010_api_key_lifecycle.sql` after `009`:

```bash
docker compose exec db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/010_api_key_lifecycle.sql
```

**Rollback:**

```sql
ALTER TABLE documents DROP CONSTRAINT IF EXISTS fk_documents_tenant_id;
-- then optionally: ALTER TABLE documents ALTER COLUMN tenant_id DROP NOT NULL;
```

> **Duplicate `004` prefixes:** Documented in [Database migrations](#database-migrations).
> Do not add another `004_*` file; use the next unused number (`015_*` at time of writing).

### Hybrid retrieval (`content_tsv`)

See [Database migrations](#database-migrations) for applying files on existing volumes.

To enable vector + PostgreSQL full-text hybrid search (issue P3B-1), apply the migration
and set `HYBRID_RETRIEVAL_ENABLED=true` in `backend/.env`:

```bash
docker compose exec db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/004_hybrid_retrieval.sql
```

Or paste the contents of `backend/db/init/004_hybrid_retrieval.sql` into `psql`.
The column `content_tsv` is a generated `tsvector` from `chunk_text`; existing chunks
are backfilled automatically. Hybrid retrieval requires the SQLAlchemy/PostgreSQL
backend (`APP_ENV=development` or `APP_ENV=test` with `DATABASE_URL`).

### Durable session storage (`sessions`, `session_documents`)

See [Database migrations](#database-migrations) for applying files on existing volumes.

If your Postgres volume was created before issue #386, apply the session persistence
migration manually (fresh Docker volumes and CI apply all init scripts automatically):

```bash
docker compose exec db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
    -f /docker-entrypoint-initdb.d/007_sessions.sql
```

Or paste the contents of `backend/db/init/007_sessions.sql` into `psql`.

### Ports

- **8000** — HTTP API. Expose behind a reverse proxy or load balancer.
- **5432** — Postgres (development Compose only). Production Compose does not publish Postgres on the host; use `docker compose exec db psql` when needed.



### Distributed rate limiting

The API uses Redis as the storage backend for `slowapi` rate limiting when
`REDIS_URL` is configured. Rate-limit buckets are shared through Redis, so
multiple API workers/processes enforce the same tenant-scoped limits.

Rate-limit keys are tenant-scoped:

```text
tenant:{tenant_id}
```

### Queue persistence

The default in-memory queue does not persist across restarts. In production
(`APP_ENV=production`), Redis is the default queue backend. For local development
with Redis, set `QUEUE_BACKEND=redis` and provide `REDIS_URL`.

### Redis queue integration tests

`backend/tests/test_queue_redis.py` exercises the real Redis-backed ingestion
queue. Tests are marked with `redis_integration` and skip automatically when
Redis is not reachable.

With Docker (same Redis URL and logical DB index as CI):

```bash
make tests
# or only the Redis integration suite:
docker compose run --rm tests pytest -m redis_integration -v
```

Without Docker (requires Postgres and Redis running locally):

```bash
cd backend && REDIS_URL=redis://localhost:6379/15 pytest -m redis_integration -v
```

Use logical DB `15` for test isolation (see `docker-compose.yml` `tests` service).
Without `REDIS_URL`, tests default to `redis://localhost:6379/0`.

---

## CI

Pull requests and pushes to `main` run the GitHub Actions workflow in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml): backend tests
against a real pgvector Postgres instance and Redis (with all
[database migrations](#database-migrations) applied), including
`redis_integration` tests in `test_queue_redis.py`, plus a Docker build of
the API image.

To run tests locally in the same Docker environment as CI:

```bash
make tests
```

To run tests directly without Docker (requires Postgres running and
env vars set):

```bash
cd backend && pytest tests/ -v --tb=short
```

---

## Frontend

The frontend demo lives in `frontend-demo/` and is a Next.js app. It is a
**non-core reference UI** for exercising the backend — not a production client.

### Demo pages

| Page | Path | What it demonstrates |
| --- | --- | --- |
| Chat | `/chat` | Upload, Postgres-backed session sidebar, retrieval controls, retrieval inspector, cited answers (`POST /chat/stream` with sync fallback) |
| Batch | `/batch` | Compare and synthesize modes; document list loaded from `GET /documents` |
| Status | `/status` | Live backend health and system metrics |

Navigation groups Demo and Docs links in the header. Structured API errors from
the backend are surfaced in the UI.

**Note:** Ingestion progress uses SSE (`/documents/{id}/status/stream`) with
polling fallback. While a document is `queued`, the backend may return
`queue_position` (1 = next to process); the demo surfaces this on attachment
chips when position is greater than 1.

Chat in the demo uses `/chat/stream` when streaming is enabled on the backend,
with fallback to non-streaming `POST /chat`. Historical messages loaded from
the session API may still use the character animation in `MessageList.tsx` for
display polish; live responses stream tokens when SSE is available.

The batch demo loads documents from `GET /documents` (tenant-scoped) rather
than a browser-local document registry.

### Prerequisites

- Node.js 18+
- npm or yarn

### Setup

```bash
cd frontend-demo
npm install
```

### Environment

Create `frontend-demo/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Start dev server

```bash
npm run dev
```

Frontend runs at http://localhost:3000

### Start backend + frontend together

```bash
make          # Opens browser tabs when services are ready
make dev      # Same without opening tabs
make quickstart  # Run setup first, then start with browser tabs
```

This starts the backend Docker stack and the non-containerized frontend dev server in the foreground. API keys are configured through `make setup` or `make quickstart` — see [README.md — Quick Start](README.md#-quick-start).

---

## Advanced Local Development

### Option 1: Docker Database Only

```bash
docker compose up -d db

cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
export APP_ENV="development"
export GEN_AI_KEY="your-key"
# Or for OpenAI: export OPENAI_API_KEY="your-key" LLM_PROVIDER=openai EMBEDDING_PROVIDER=openai
# Or for Ollama: export LLM_PROVIDER=ollama EMBEDDING_PROVIDER=ollama
# Or for Anthropic: export ANTHROPIC_API_KEY="your-key" LLM_PROVIDER=anthropic

uvicorn main:app --reload --port 8000
```

### Option 2: Fully Local PostgreSQL

```bash
createdb chatvector_dev
# Apply all migrations — see Database migrations
for f in $(ls backend/db/init/*.sql | sort); do
  psql -d chatvector_dev -v ON_ERROR_STOP=1 -f "$f"
done

export DATABASE_URL="postgresql+asyncpg://localhost:5432/chatvector_dev"
export APP_ENV="development"
export GEN_AI_KEY="your-key"

uvicorn main:app --reload --port 8000
```

---

## Git Workflow

```bash
git checkout main
git pull upstream main
git checkout -b feat/your-feature
```

Commit:

```bash
git add .
git commit -m "feat: add feature"
git push -u origin feat/your-feature
```

Before PR:

```bash
git fetch upstream
git rebase upstream/main
git push --force-with-lease
```

Open PR → `your-fork → main`

Clean up local branches after merging:

```bash
make cleanup
```

---

## Common Tasks

### Access Database

```bash
docker compose exec db psql -U postgres -d postgres
```

### Reset Database

```bash
docker compose down -v
docker compose up -d db
```

### Health Check

```bash
curl http://localhost:8000/status
```

### View Queue Stats

```bash
curl http://localhost:8000/queue/stats
```

### Inspect query transformation traces

Chat endpoints accept an opt-in `debug_retrieval` flag (default `false`). When
enabled, responses include a `retrieval_debug` object describing how the user
question was transformed before embedding and search:

- `original_query` — the raw user question
- `history_resolved_query` — standalone rewrite after session history resolution (when it differs)
- `history_considered` — retrieval-window messages actually considered, each `{role, content_preview}`
- `history_resolution_applied` — true only when the resolution LLM ran and returned text
- `history_resolution_skipped_reason` — why the gate skipped the LLM (`empty_history`, `standalone_question`, `topic_switch`, `disabled`, `compare_skip`)
- `history_resolution_fallback_reason` — `llm_failure` when resolution was attempted and the original question was kept
- `history_resolution_latency_ms` — time spent in the resolution LLM call, when it ran
- `history_window` — `{retrieval, generation}` message counts actually used
- `history_truncation` — messages dropped by the windows, generation character trimming, preview trimming, and the resolved `max_context_chars`
- `history_config_applied` — present when the request sent a `history` object
- `transformed_queries` — final query list embedded and searched
- `transformation_strategy` — active strategy (`rewrite`, `expand`, or `stepback`) when a strategy ran
- `effective_retrieval_query` — primary retrieval string (first transformed query), used for keyword search and reranking
- `effective_config` — resolved retrieval settings with `value` and `source` (`request`, `preset`, or `env`) for each field, plus the process `max_context_chars` annex
- `reranker` — present only when reranking ran: `provider`, `model` (hosted providers), `latency_ms`, `candidates_sent`, and `fallback_reason` when the provider failed and the pre-rerank order was kept
- `timing_ms` — transform, embed, search, rerank, context, and total milliseconds

Pass the flag as a JSON body field or query parameter:

```bash
curl -X POST "http://localhost:8000/chat?debug_retrieval=true" \
  -H "Content-Type: application/json" \
  -d '{"question":"What about it?","doc_id":"<uuid>","session_id":"<session-id>"}'
```

The same flag works on `/chat/stream` (included on the `complete` SSE event)
and `/chat/batch` (per result item). Normal clients are unaffected when the
flag is omitted.

Query transformation itself is controlled by `QUERY_TRANSFORMATION_ENABLED` and
`QUERY_TRANSFORMATION_STRATEGY` — see `backend/.env.example`. History-aware
retrieval is separate: the default path spends an extra LLM call only on
follow-ups the gate selects, not on every session turn. Set
`HISTORY_AWARE_RETRIEVAL_DEFAULT=false` to resolve history only when query
transformation is enabled.

---

## Environment Variables

Create `backend/.env` from the example:

```bash
cp backend/.env.example backend/.env
```

Minimum required for local development:

```env
APP_ENV=development
GEN_AI_KEY=your_google_ai_studio_key
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
LOG_LEVEL=INFO

# Provider selection (optional — defaults to gemini)
# LLM_PROVIDER=gemini          # gemini | openai | ollama | anthropic
# EMBEDDING_PROVIDER=gemini    # gemini | openai | ollama | voyage
# See backend/.env.example for all provider options
```

### Mixed LLM and embedding providers

LLM and embedding providers are configured independently via `LLM_PROVIDER` and
`EMBEDDING_PROVIDER`. Any supported LLM can pair with any supported embedding
provider — for example Claude for generation with Voyage for embeddings:

```env
LLM_PROVIDER=anthropic
EMBEDDING_PROVIDER=voyage
ANTHROPIC_API_KEY=your_anthropic_api_key
VOYAGE_API_KEY=your_voyage_api_key
```

| Role | Providers |
|------|-----------|
| LLM (`LLM_PROVIDER`) | `gemini`, `openai`, `ollama`, `anthropic` |
| Embedding (`EMBEDDING_PROVIDER`) | `gemini`, `openai`, `ollama`, `voyage` |

All 16 combinations are supported. Credential requirements are per provider
(see `backend/.env.example`). On startup (except when `APP_ENV=test`), the
backend validates provider names, required API keys, and streaming compatibility
before accepting traffic. Invalid configurations fail fast with actionable
error messages.

> **Note:** Changing `EMBEDDING_PROVIDER` or `EMBEDDING_MODEL` changes vector
> dimensions. Re-embed documents or use a fresh database after switching
> embedding providers.

Optional embedding cache (off by default). See `backend/.env.example` for
`ENABLE_EMBEDDING_CACHE`, `EMBEDDING_CACHE_KEY_PREFIX`,
`EMBEDDING_CACHE_TTL_SECONDS`, `EMBEDDING_CACHE_INCLUDE_TENANT`, and
`EMBEDDING_CACHE_REDIS_TIMEOUT_SEC`. Cache Redis reads use that short timeout
and fail open; they do not use `REDIS_SOCKET_TIMEOUT_SEC`. `/status` LLM and
embedding probes use `LLM_HEALTH_CHECK_TIMEOUT_SEC` and
`EMBEDDING_HEALTH_CHECK_TIMEOUT_SEC` (default 10 seconds each).

### Prompt persona

The reference demo runs `PROMPT_PERSONA=default` — the same persona as the
backend code default (`backend/core/config.py`) and `backend/.env.example`.
Docker Compose sets it explicitly on the `api` service, so the stock stack
does not depend on a private `backend/.env`. A deployment may still override
`PROMPT_PERSONA` with any value in `VALID_PERSONAS` (`default`, `concise`,
`conversational`, `academic`, `technical`). `load_dotenv` does not override
variables already in the process environment, so an explicit Compose or
process value wins over a `backend/.env` line.

Audit 2 and Audit 3 ran `conversational` because a private environment
overrode the default. That persona is warmer and more verbose than `default`
and does not require citations; it is not the product default. Any future
Gemini quality baseline must record the persona that was actually active for
its run, including an override if one was used, and must not assume the audit
environment's `conversational` setting.

The chat UI has no persona selector; persona stays process configuration.

### Authentication variables

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `development`/`test` bypass auth; `production` enforces Bearer key |
| `DEV_TENANT_ID` | `dev` | Tenant ID attributed to all requests when auth bypass is active |

In **development** and **test** mode, the backend automatically ensures a
`tenants` row exists for `DEV_TENANT_ID` on startup (idempotent — safe across
restarts). No API key is created and none is required while the bypass is
active. A fresh `docker compose up` after `docker compose down -v` therefore
works without running the tenant CLI first.

In **production**, tenants and API keys are **not** auto-created. Use the CLI
below before pointing clients at the API.

> **Warning:** A startup log message (`Authentication bypass is ACTIVE`) is
> printed whenever `APP_ENV` is not `production`. If you see this message on a
> shared or public server, set `APP_ENV=production` immediately.

To generate a tenant and API key for production (or when testing real auth locally):

```bash
cd backend
python -m backend.cli create-tenant-key --tenant "My Org" --tenant-id my-org
```

Set the printed `cv_live_…` key in all API clients as the Bearer token.

### Horizontal API scaling variables

| Variable | Default | Description |
|---|---|---|
| `MULTI_API_INSTANCE` | `false` | Enables more than one API container. Requires Redis + `ARTIFACT_STORAGE=s3`. |
| `TENANT_REGISTRY_DISABLED` | `true` when `MULTI_API_INSTANCE` is set | Bypass the process-local tenant document cache (DB is authoritative). |
| `STALE_RECONCILE_LOCK_TTL_SECONDS` | `600` | Redis lock TTL so only one replica runs `fail_stale_documents_global`. |

See `backend/.env.example` for the full list including chunking
strategy, rate limits, LLM timeouts, prompt configuration, and
observability settings.

---

## Troubleshooting

### Port Already in Use

```bash
lsof -ti:8000 | xargs kill -9
```

### Database Issues

```bash
docker compose logs db
docker compose ps
```

### Reset Everything

```bash
docker compose down -v
docker compose up --build
```

### API Docs Not Showing

`/docs` is disabled when `APP_ENV=production`. Set `APP_ENV=development`
in `backend/.env` for local development.

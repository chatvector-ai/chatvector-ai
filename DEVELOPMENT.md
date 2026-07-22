# Development Guide

## Table of Contents

- [API Access](#api-access)
- [Quick Start](#quick-start)
- [Docker Reference](#docker-reference)
- [Database Initialization](#database-initialization)
- [Database migrations](#database-migrations)
- [Working with the Database Layer](#working-with-the-database-layer)
- [Ingestion Queue](#ingestion-queue)
- [Tests](#tests)
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
| Order | Lexical sort on the filename (`001` … `008` today; next is `009_*`) |
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
```

> **Do not add another `004_*` file.** Use the next unused number (`009_*` at
> time of writing). The duplicate `004` pair is historical; chat history always
> runs before hybrid retrieval because of alphabetical sort.

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

1. Pick the next number — check `backend/db/init/`; use `009_*` if
   `008_schema_migrations.sql` is the latest.
2. Add `backend/db/init/009_your_change.sql` with idempotent DDL (and any
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
worker pool. Poll `GET /documents/{id}/status` for progress.

**Status flow:**

```
queued → extracting → chunking → embedding → storing → completed
                                                      ↘ failed
```
### Status updates: poll vs stream

There are two ways to track ingestion progress after upload:

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
| `complete` | JSON object | Final metadata: `type`, `session_id`, `sources`, `latency_ms`, `model`. |
| `done` | `[DONE]` | **Deprecated.** Retained for backward compatibility; emitted after `complete`. |
| `error` | JSON object | `type`, `code`, and `message`. Valid JSON — not a plain string. |

Example successful sequence:

```text
event: token
data: "Hello"

event: complete
data: {"type":"complete","session_id":"...","sources":[...],"latency_ms":1234,"model":"..."}

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

---

```env
QUEUE_WORKER_COUNT=3      # concurrent background workers (1–5)
QUEUE_MAX_SIZE=100        # max pending jobs; uploads beyond this return 503
QUEUE_EMBEDDING_RPS=2.0   # max embedding API calls/sec across workers
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

## Deployment

### Local development

For day-to-day work use the [Quick Start](#quick-start) flow
(`make quickstart`, `make`, or `docker compose up --build`). That stack
mounts live backend code and uses development defaults.

### Local production simulation

`docker-compose.prod.yml` is a **standalone** file — it does not
extend or merge with `docker-compose.yml`. It disables code bind
mounts, runs multi-worker uvicorn, enables JSON logging, and applies
resource limits.

```bash
# Copy and configure production env
cp backend/.env.example backend/.env.prod
# Edit .env.prod with real values

# Start production stack
make prod-up
# or
docker compose -f docker-compose.prod.yml up -d
```

Docker Compose expands `${VAR}` from your process environment or a
`.env` file in the project root. If values are only in
`backend/.env.prod`, either `export` them first or pass
`--env-file backend/.env.prod` to the `docker compose` command.

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

**Bootstrap a tenant and API key** (run once per environment):

```bash
cd backend
python -m backend.cli create-tenant-key --tenant "My Org" --tenant-id my-org
```

The raw API key (`cv_live_…`) is displayed **once** and is never stored.
Record it immediately. Use it as `Authorization: Bearer <raw-key>` in all requests.

**Rollback:**

```sql
ALTER TABLE documents DROP CONSTRAINT IF EXISTS fk_documents_tenant_id;
-- then optionally: ALTER TABLE documents ALTER COLUMN tenant_id DROP NOT NULL;
```

> **Duplicate `004` prefixes:** Documented in [Database migrations](#database-migrations).
> Do not add another `004_*` file; use the next unused number (`009_*` at time of writing).

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
- **5432** — Postgres. Keep internal to your network in production.

### Queue persistence

The default in-memory queue does not persist across restarts. In production
(`APP_ENV=production`), Redis is the default queue backend. For local development
with Redis, set `QUEUE_BACKEND=redis` and provide `REDIS_URL`.

---

## CI

Pull requests and pushes to `main` run the GitHub Actions workflow in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml): backend tests
against a real pgvector Postgres instance (with all [database migrations](#database-migrations)
applied), plus a Docker build of the API image.

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
| Chat | `/chat` | Upload, session sidebar, retrieval controls, retrieval inspector, cited answers (`POST /chat`) |
| Batch | `/batch` | Compare and synthesize modes against multiple documents |
| Status | `/status` | Live backend health and system metrics |

Navigation groups Demo and Docs links in the header. Structured API errors from
the backend are surfaced in the UI.

**Note:** Ingestion progress uses SSE (`/documents/{id}/status/stream`) with
polling fallback. While a document is `queued`, the backend may return
`queue_position` (1 = next to process); the demo surfaces this on attachment
chips when position is greater than 1.

Chat in the demo still uses non-streaming `POST /chat` even though the backend
`/chat/stream` endpoint and Python SDK streaming are available. The chat UI
simulates typing with a character-by-character animation in
`MessageList.tsx` — this is **not** real SSE token streaming.

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
- `transformed_queries` — final query list embedded and searched
- `transformation_strategy` — active strategy (`rewrite`, `expand`, or `stepback`) when transformation is enabled

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
`QUERY_TRANSFORMATION_STRATEGY` — see `backend/.env.example`.

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

> **Warning:** A startup log message (`⚠️ Authentication bypass is ACTIVE`) is
> printed whenever `APP_ENV` is not `production`. If you see this message on a
> shared or public server, set `APP_ENV=production` immediately.

To generate a tenant and API key for production (or when testing real auth locally):

```bash
cd backend
python -m backend.cli create-tenant-key --tenant "My Org" --tenant-id my-org
```

Set the printed `cv_live_…` key in all API clients as the Bearer token.

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

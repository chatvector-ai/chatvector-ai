# Development Guide

## Table of Contents

- [API Access](#api-access)
- [Quick Start](#quick-start)
- [Docker Reference](#docker-reference)
- [Database Initialization](#database-initialization)
- [Working with the Database Layer](#working-with-the-database-layer)
- [Embedding Queue Architecture](#embedding-queue-architecture)
- [Tests](#tests)
- [Advanced Local Development](#advanced-local-development)
- [Git Workflow](#git-workflow)
- [Common Tasks](#common-tasks)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)

---

## API Access

Backend: http://localhost:8000  
API Docs (Swagger UI): http://localhost:8000/docs  
Database: PostgreSQL with pgvector (port 5432)

---

## Quick Start

Start the full backend stack (API + database):

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
docker exec -it chatvector-db psql -U postgres -d postgres
```


### Makefile Commands

To simplify Docker workflows, the project includes a `Makefile` with short, memorable commands.

These are wrappers around standard `docker compose` commands.  
You can still use Docker directly if preferred.


```bash
make up      # Start containers (detached)
make build   # Rebuild and start containers
make down    # Stop containers
make reset   # Stop containers and remove volumes
make logs    # Follow API logs
make db      # Open Postgres shell
make help    # Show all available commands
```

### Frontend (Local Node )
---

## Database Initialization

The database initializes automatically with:

- `pgvector` extension
- `documents` table
- `document_chunks` table
- `match_chunks` similarity function

Verify setup:

```bash
docker exec -it chatvector-db psql -U postgres -d postgres

\dx
\dt

SELECT * FROM match_chunks(
    array_fill(0::real, ARRAY[3072])::vector,
    1
) LIMIT 0;

\q
```

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

### 2. Implement in both services

- `db/sqlalchemy_service.py` (development)
- `db/supabase_service.py` (production)

### 3. Use via factory

```python
from app.db import new_operation

result = await new_operation("test")
```

The factory automatically:

- Selects the correct environment
- Applies retry logic
- Handles logging

---

## Embedding Queue Architecture

`POST /upload` returns in under 500 ms regardless of file size. The heavy
work — text extraction, chunking, embedding, and storage — happens in the
background via an in-memory asyncio queue drained by a pool of worker tasks.

### Upload flow

```
Client                   API                       Worker pool
  │                       │                             │
  │── POST /upload ───────▶│                             │
  │                       │ validate file               │
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
  │                       │                             │
  │── GET /documents/{id}/status ─────────────────────▶ │
  │◀─ {status: "completed", chunks_processed: 42} ──── │
```

Poll `GET /documents/{id}/status` for progress. While the job is still
pending, the response also includes a live `queue_position` field.

### Worker pool

Workers are plain asyncio tasks started when the application boots and
cancelled cleanly on shutdown. The pool size is set with `QUEUE_WORKER_COUNT`
(default `3`, maximum `5`).

```env
QUEUE_WORKER_COUNT=3   # number of concurrent background workers (1–5)
QUEUE_MAX_SIZE=100     # maximum pending jobs; uploads beyond this return 503
```

**When to increase workers:** if documents stay in `"queued"` status for a
long time while the server is otherwise idle, more workers will drain the
backlog faster. Keep in mind that each worker makes independent embedding
API calls, so raising `QUEUE_WORKER_COUNT` without also raising
`QUEUE_EMBEDDING_RPS` will cause workers to serialize on the rate limiter
rather than truly run in parallel.

### Token bucket rate limiter

The embedding step calls the Google Gemini API. To protect against rate-limit
errors under load, each worker must acquire a token from a shared token bucket
before calling `get_embeddings()`. Jobs that fail during extraction or
chunking (before reaching the embedding step) never consume a token.

```env
QUEUE_EMBEDDING_RPS=2.0   # max Gemini API calls per second across all workers
```

The bucket refills continuously at `QUEUE_EMBEDDING_RPS` tokens per second
with a burst capacity equal to one second of throughput. If all workers race
to embed at the same time, they queue behind the limiter and are released
at the configured rate.

**Tuning:** consult your Google AI Studio project's quota page. A typical
free-tier project allows around 2 requests/second; a paid project may allow
significantly more. Set `QUEUE_EMBEDDING_RPS` to ~80% of your actual quota
to leave headroom for the chat endpoint's embedding calls.

### Retry logic and dead-letter queue

If a worker fails at any stage, it retries the full job (extraction through
storage) up to `QUEUE_JOB_MAX_RETRIES` times. Between attempts the document
status is set to `"retrying"` so polling clients see a meaningful state
rather than a transient `"failed"`.

```env
QUEUE_JOB_MAX_RETRIES=3   # retries before a job is moved to the DLQ
```

After all retries are exhausted the job is appended to the **dead-letter
queue (DLQ)** — an in-memory list of lightweight records (no file bytes).
Inspect it at any time:

```bash
curl http://localhost:8000/queue/stats
```

```json
{
  "queue_size": 2,
  "worker_count": 3,
  "dlq_size": 1,
  "dlq": [
    {
      "doc_id": "a1b2c3d4-...",
      "file_name": "report.pdf",
      "attempt": 3,
      "error": "embedding API unavailable",
      "failed_at": "2026-03-20T21:14:05.123456+00:00"
    }
  ]
}
```

The DLQ is in-memory only — it is cleared on server restart. The document's
`status` in the database is set to `"failed"` with a `failed_stage` and
`error_message` for durable inspection via `GET /documents/{id}/status`.

### Server restart and in-flight jobs

Because the queue is in-memory, any jobs still pending or being processed at
the moment the server stops are lost. On the next startup, before workers
begin accepting new jobs, the application scans the database for documents
left in any in-progress state and bulk-updates them to `"failed"`:

| Status reset to `"failed"` on startup |
|---|
| `queued` |
| `retrying` |
| `extracting` |
| `chunking` |
| `embedding` |
| `storing` |

This ensures clients polling for a stale document receive a definitive
`"failed"` response rather than waiting indefinitely. The original file is
not retained after the upload request completes, so these documents cannot
be automatically retried — the client must re-upload.

---

## Tests

This project uses `pytest` and `pytest-asyncio`.

### Using Docker (Recommended)

```bash
docker compose run --rm tests
```

Common options:

```bash
pytest -v        # verbose
pytest -x        # stop on first failure
pytest -s        # show print statements
pytest --cov=app # coverage
```

### Running Locally

`backend/requirements.txt` installs `psycopg[binary]`, so local pytest
collection does not require a separate system `libpq` installation. If you
already have an older local environment, reinstall the backend requirements so
`psycopg` and `psycopg-binary` stay on matching versions.

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

The bundled binary wheel removes the extra `libpq` setup step, but tests that
open real PostgreSQL connections still need a running Postgres instance.

---

## Advanced Local Development

For contributors running Python directly.

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

uvicorn main:app --reload --port 8000
```

---

### Option 2: Fully Local PostgreSQL

```bash
createdb chatvector_dev
psql -d chatvector_dev -f backend/db/init/001_init.sql

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
curl http://localhost:8000/
```

---

## Environment Variables

Create `backend/.env`:

```env
GEN_AI_KEY=your_google_ai_studio_key
APP_ENV=development
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
LOG_LEVEL=INFO
```

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

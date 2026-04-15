# Development Guide

## Table of Contents

- [API Access](#api-access)
- [Quick Start](#quick-start)
- [Docker Reference](#docker-reference)
- [Database Initialization](#database-initialization)
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

The project includes a `Makefile` with short, memorable commands as
wrappers around standard `docker compose` commands.

```bash
make dev        # Start backend (detached) + frontend dev server
make up         # Start containers (detached)
make build      # Rebuild and start containers
make down       # Stop containers
make reset      # Stop containers and remove volumes
make logs       # Follow API logs
make db         # Open Postgres shell
make tests      # Run tests via Docker (docker compose run --rm tests)
make prod-up    # Start production stack (standalone compose)
make prod-down  # Stop production stack
make prod-build # Rebuild and start production stack
make clean      # Remove containers, volumes, and orphans
make cleanup    # Delete all local branches except main
make sync       # Sync fork with upstream main
make help       # Show all available commands
```

Direct `docker compose` usage still works if preferred.

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

-- Dimension depends on the configured embedding model
-- (e.g. 3072 for Gemini, 1536 for OpenAI, 768 for Ollama nomic-embed-text)
SELECT * FROM match_chunks(
    array_fill(0::real, ARRAY[<EMBEDDING_DIM>])::vector,
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
import db

result = await db.new_operation("test")
```

The factory automatically selects the correct environment, applies
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

**Key config:**

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

> **Note:** The current queue is in-memory and does not persist across
> restarts. Redis-backed durability is planned in [#123](https://github.com/chatvector-ai/chatvector-ai/issues/123).

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

`backend/requirements.txt` installs `psycopg[binary]`, so local pytest
collection does not require a separate system `libpq` installation.

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
(`docker compose up --build` or `make up` / `make dev`). That stack
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
| `DATABASE_URL`        | **Required** | `postgresql+asyncpg://…` pointing at your Postgres instance     |
| `APP_ENV=production`  | **Required** | Disables `/docs`, enables JSON logging                          |
| `CORS_ORIGINS`        | **Required** | Comma-separated list of allowed browser origins                 |
| `POSTGRES_USER`       | **Required** | Used by `db` service in `docker-compose.prod.yml`               |
| `POSTGRES_PASSWORD`   | **Required** | As above                                                        |
| `POSTGRES_DB`         | **Required** | As above                                                        |
| `LOG_LEVEL`           | Optional     | Default: `INFO`                                                 |
| `LOG_FORMAT`          | Optional     | `TEXT` or `JSON` (default: `TEXT`; use `JSON` for log shipping) |
| `QUEUE_WORKER_COUNT`  | Optional     | Default: `3`                                                    |
| `QUEUE_EMBEDDING_RPS` | Optional     | Default: `2.0`                                                  |
| `LLM_HTTP_TIMEOUT_MS` | Optional     | Default: `60000`                                                |
| `CHUNKING_STRATEGY`   | Optional     | `fixed` (default), `paragraph`, or `semantic`                   |

See `backend/.env.example` for the full list of tunables.

### Upgrading from a pre-#167 Deployment

Versions before PR #167 created `document_chunks.embedding` as `vector(3072)`.
The current schema uses a dimensionless `vector` column to support multiple
embedding providers.

**Option A — Run the migration (keeps existing data):**

```bash
docker compose exec db psql -U postgres -d postgres \
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

### Ports

- **8000** — HTTP API. Expose behind a reverse proxy or load balancer.
- **5432** — Postgres. Keep internal to your network in production.

### Queue persistence

The current in-memory queue does not persist across restarts. Plan
for this in production deployments until Redis (#123) lands.

---

## CI

Pull requests and pushes to `main` run the GitHub Actions workflow in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml): backend tests
against a real pgvector Postgres instance, plus a Docker build of
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

The frontend demo lives in `frontend-demo/` and is a Next.js app.

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
make dev
```

This starts the backend stack in detached mode and the frontend dev
server in the foreground.

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

uvicorn main:app --reload --port 8000
```

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
# LLM_PROVIDER=gemini          # gemini | openai | ollama
# EMBEDDING_PROVIDER=gemini    # gemini | openai | ollama
# See backend/.env.example for all provider options
```

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

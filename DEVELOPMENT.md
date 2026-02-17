# Development Guide

## Table of Contents

- [API Access](#api-access)
- [Quick Start](#quick-start)
- [Docker Reference](#docker-reference)
- [Database Initialization](#database-initialization)
- [Working with the Database Layer](#working-with-the-database-layer)
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

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

(PostgreSQL must be running.)

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

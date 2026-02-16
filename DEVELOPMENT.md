# Developer Guide

## Table of Contents

- [API Access](#api-access)
- [Quick Start](#quick-start)
- [Tests](#tests)
- [Backend Development](#backend-development)
- [Git Workflow](#git-workflow)
- [Common Tasks](#common-tasks)
- [Troubleshooting](#troubleshooting)

---

## API Access

Backend: http://localhost:8000  
API Docs (Swagger UI): http://localhost:8000/docs  
Database: PostgreSQL with pgvector on port 5432
Frontend: http://localhost:3000

---

## Quick Start

### Backend (Docker - Recommended)

#### Docker Commands

```bash
# Rebuild backend after dependency changes
docker compose build api

# Start the backend stack (API + database)
docker compose up api db

# Start everything (including test container if needed)
docker compose up

# Start just the database (for local Python development)
docker compose up db

# Stop all containers
docker compose down

# Stop and remove data (clean slate) - WARNING: deletes all database data
docker compose down -v

# View backend logs
docker compose logs -f api

# View database logs
docker compose logs -f db

# Check running services
docker compose ps
# Should show: api, db

# Restart containers
docker compose restart

# Access PostgreSQL directly (useful for debugging)
docker exec -it chatvector-db psql -U postgres -d postgres

# Run a specific service (e.g., just the database)
docker compose up db
```

---

## Database Initialization

The database is automatically initialized with:

- pgvector extension for vector similarity search
- `documents` table for file metadata
- `document_chunks` table with `vector(3072)` embeddings (matching Gemini)
- `match_chunks` function for similarity search

Verify the setup:

```bash
# Connect to PostgreSQL
docker exec -it chatvector-db psql -U postgres -d postgres

# Check if vector extension is enabled
\dx

# List tables
\dt

# Test the match_chunks function (returns 0 rows, but verifies it exists)
SELECT * FROM match_chunks(array_fill(0::real, ARRAY[3072])::vector, 1) LIMIT 0;

# Exit
\q
```

---

## Tests

This project uses `pytest` and `pytest-asyncio` for async tests.

### Using Docker (Recommended)

```bash
# Run all tests
docker compose run --rm tests

# Run with verbose output
docker compose run --rm tests pytest -v

# Run specific test file
docker compose run --rm tests pytest tests/test_retry.py -v

# Run specific test function
docker compose run --rm tests pytest tests/test_retry.py::test_retry_success_on_third_try -v

# Stop on first failure
docker compose run --rm tests pytest tests/ -v -x

# Show print statements
docker compose run --rm tests pytest tests/test_retry.py -v -s
```

### Running Tests Locally

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Run tests (requires PostgreSQL running)
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Backend Development

(Local Python - Advanced)

For contributors who prefer running Python directly (without Docker):

### Prerequisites

- PostgreSQL 16+ with pgvector installed locally OR use Docker for database only
- Python 3.11+

---

### Option 1: Use Docker for Database Only

```bash
# Start only PostgreSQL in Docker
docker compose up -d db

# Run backend locally
cd backend
python -m venv venv
source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
export APP_ENV="development"
export GEN_AI_KEY="your-key-here"

# Run with auto-reload
uvicorn main:app --reload --port 8000
```

---

### Option 2: Fully Local Setup

```bash
# Install PostgreSQL locally (method varies by OS)
# brew install postgresql pgvector  # Mac example

# Create database
createdb chatvector_dev

# Run init script
psql -d chatvector_dev -f backend/db/init/001_init.sql

# Set up Python
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://localhost:5432/chatvector_dev"
export APP_ENV="development"
export GEN_AI_KEY="your-key-here"

# Run
uvicorn main:app --reload --port 8000
```

---

## Git Workflow

### 0. One-Time Setup

```bash
git clone https://github.com/<your-username>/chatvector-ai.git
cd chatvector-ai

git remote add upstream https://github.com/chatvector-ai/chatvector-ai.git
git remote -v
```

Expected:

```
origin    https://github.com/<your-username>/chatvector-ai.git (fetch)
origin    https://github.com/<your-username>/chatvector-ai.git (push)
upstream  https://github.com/chatvector-ai/chatvector-ai.git (fetch)
upstream  https://github.com/chatvector-ai/chatvector-ai.git (push)
```

---

### 1. Create Feature Branch

```bash
git checkout main
git pull upstream main

git checkout -b feat/your-feature-name
```

---

### 2. Make Changes & Commit

```bash
git add .
git commit -m "feat: add document search endpoint"
git push -u origin feat/your-feature-name
```

---

### 3. Update Branch Before PR

```bash
git fetch upstream
git rebase upstream/main

git add .
git rebase --continue

git push --force-with-lease
```

---

### 4. Submit Pull Request

- Open PR: `your-fork:feature-branch → upstream:main`
- Use PR template
- Link related issues
- Wait for CI checks
- Request review

---

## Common Tasks

### Database Operations

```bash
docker compose exec db psql -U postgres -d postgres

\dt
\d documents
\d document_chunks
SELECT * FROM documents LIMIT 5;
SELECT COUNT(*) FROM document_chunks;

SELECT * FROM match_chunks(
    (SELECT embedding FROM document_chunks LIMIT 1),
    5
);

\q
```

---

### Reset Database

```bash
docker compose down -v
docker compose up -d db

docker compose logs db | grep "database system is ready"
```

---

### Test API Endpoints

```bash
# Health check
curl http://localhost:8000/

# Upload a document
curl -X POST -F "file=@sample.pdf" http://localhost:8000/upload

# Chat with document
curl -X POST "http://localhost:8000/chat?doc_id=UUID&question=your+question"
```

Expected upload response:

```json
{
  "message": "Uploaded",
  "document_id": "uuid-here",
  "chunks": 42
}
```

---

### Check Logs

```bash
docker compose logs -f api
docker compose logs -f db
docker compose logs tests
```

---

### Environment Variables

Create a `.env` file in `backend/`:

```env
GEN_AI_KEY=your_google_ai_studio_api_key_here

APP_ENV=development
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/postgres
LOG_LEVEL=INFO
```

Docker provides database credentials automatically; only `GEN_AI_KEY` is required.

---

## Troubleshooting

### Port Already in Use

```bash
lsof -ti:8000 | xargs kill -9
```

Or use another port:

```bash
uvicorn main:app --reload --port 8001
```

---

### Database Connection Errors

```bash
docker compose ps
docker compose logs db
docker compose logs db | grep "ready to accept connections"

docker exec -it chatvector-db psql -U postgres -d postgres -c "SELECT 1"
```

---

### GEN_AI_KEY Errors

- Ensure `.env` exists in `backend/`
- Verify: `grep GEN_AI_KEY backend/.env`
- Restart API: `docker compose restart api`
- Check logs: `docker compose logs api | grep -i key`

---

### Schema Issues

```bash
docker compose exec db psql -U postgres -d postgres -c "\dt"
docker compose exec db psql -U postgres -d postgres -c "\dx"

docker compose down -v
docker compose up -d db
```

---

### Test Import Errors

```bash
docker compose run --rm tests env | grep PYTHONPATH
docker compose run --rm tests pytest -v --tb=short
```

---

### Container Won't Start

```bash
docker compose config
docker compose ps -a

docker compose down -v
docker compose up -d db
docker compose up api
```

---

### Slow Vector Searches

```bash
docker compose exec db psql -U postgres -d postgres -c "\di"

docker compose exec db psql -U postgres -d postgres -c "
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding
ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
"
```

---

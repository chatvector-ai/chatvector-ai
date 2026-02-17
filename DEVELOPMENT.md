# Development Guide

Quick reference for day-to-day development workflows. For initial setup, see the main README.

---

## 📚 Table of Contents

- [Quick Start](#-quick-start)
- [API Access](#-api-access)
- [Tests](#-running-tests)
- [Backend Development](#-backend-development-local-python---advanced)
- [Git Workflow](#-git-workflow)
- [Common Tasks](#-common-tasks)
- [Troubleshooting](#-troubleshooting)

## Quick Start

### Backend (Docker - Recommended)

```bash
# Start backend + PostgreSQL
docker compose up chatvector-api chatvector-db

# Stop backend and database
docker compose down

# Stop and remove data (clean slate)
docker compose down -v

# View backend logs
docker compose logs -f chatvector-api

# Rebuild backend after dependency changes
docker compose build chatvector-api

# Check running services
docker compose ps
# Should show: chatvector-api, chatvector-db

# Restart containers
docker compose restart
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

```bash
cd frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

---

## API Access

- **Backend:** [http://localhost:8000](http://localhost:8000)
- **Frontend:** [http://localhost:3000](http://localhost:3000) (optional, for testing)
- **API Docs (Swagger UI):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Database:** PostgreSQL on port 5432

---

## Running Tests

This project uses `pytest` and `pytest-asyncio` for async tests.

### Using Docker

Run all tests in a one-off container:

```bash
docker-compose run --rm tests
```

## 🔧 Backend Development (Local Python - Advanced)

```bash
cd backend

# Create/activate virtual environment
python -m venv venv
source venv/bin/activate  # Mac/Linux
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn main:app --reload --port 8000
```

---

## Git Workflow

### 0. One-Time Setup (Required)

```bash
# Clone your fork
git clone https://github.com/<your-username>/chatvector-ai.git
cd chatvector-ai

# Add upstream (main project repo)
git remote add upstream https://github.com/chatvector-ai/chatvector-ai.git

# Verify remotes
git remote -v
```

### Expected output

```bash
origin    https://github.com/<your-username>/chatvector-ai.git (fetch)
origin    https://github.com/<your-username>/chatvector-ai.git (push)
upstream  https://github.com/chatvector-ai/chatvector-ai.git (fetch)
upstream  https://github.com/chatvector-ai/chatvector-ai.git (push)
```

### 1. Create Feature Branch

```bash
# Update local main
git checkout main
git pull upstream main

# Create descriptive branch
git checkout -b feat/your-feature-name
# or: fix/bug-description, docs/topic-update
```

### 2. Make Changes & Commit

```bash
# Stage changes
git add .

# Commit with clear message
git commit -m "feat: add document search endpoint"

# Push to your fork
git push -u origin feat/your-feature-name
```

### 3. Update Branch (Before PR)

```bash
# Get latest from main
git fetch upstream

# Rebase to avoid merge commits
git rebase upstream/main

# Resolve any conflicts, then continue
git add .
git rebase --continue

# Force push (safe for your branch only)
git push --force-with-lease
```

### 4. Submit Pull Request

- Go to: `your-fork:feature-branch → upstream:main`
- Use PR template
- Link related issues
- Wait for CI checks
- Request review

---

## Common Tasks

### Database Access

```bash
# Connect to PostgreSQL
docker compose exec chatvector-db psql -U postgres -d chatvector

# Run SQL
\dt  # List tables
SELECT * FROM documents LIMIT 5;
\q   # Quit
```

### Test API Endpoints

```bash
# Health check
curl http://localhost:8000/

# Upload a document
curl -X POST -F "file=@sample.pdf" http://localhost:8000/upload

# Chat with document
curl -X POST "http://localhost:8000/chat?doc_id=UUID&question=your+question"
```

---

## Troubleshooting

### "Port already in use"

```bash
# Find and kill process
lsof -ti:8000 | xargs kill -9  # Backend
```

### Database connection errors

```bash
# Reset database
docker compose down -v
docker compose up chatvector-db

# Wait for PostgreSQL to be ready
docker compose logs chatvector-db | grep "ready to accept"
```

### "No API_KEY found"

- Check `.env` file exists
- Verify `GEMINI_API_KEY` is set
- Restart backend container: `docker compose restart`

## Upload Atomicity (Issue #63)

- `/upload` now persists the document record and chunk rows as one logical operation.
- In `development`, this uses a single SQLAlchemy transaction.
- In `production` (Supabase mode), if chunk insertion fails after document creation, the backend performs compensating cleanup to delete the orphaned document/chunks.

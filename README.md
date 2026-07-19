# ChatVector

### Open-Source Backend-First RAG Engine for Document Intelligence

ChatVector is an open-source Retrieval-Augmented Generation (RAG) engine for ingesting, indexing, and querying unstructured documents such as PDFs and text files.

Think of it as an engine developers can use to build document-aware applications — such as research assistants, contract analysis tools, or internal knowledge systems — without having to reinvent the RAG pipeline.

<p>
  <img src="https://img.shields.io/badge/Status-Active-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen" alt="PRs Welcome">
  <img src="https://img.shields.io/badge/AI-RAG%20Engine-orange" alt="AI RAG">
  <img src="https://github.com/chatvector-ai/chatvector-ai/actions/workflows/ci.yml/badge.svg" alt="CI">
</p>

![Python Version](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=github)
![FastAPI Version](https://img.shields.io/badge/FastAPI-0.121-green?style=for-the-badge&logo=github)

---

⭐ **Star the repo to follow progress and support the project!**

[![GitHub stars](https://img.shields.io/github/stars/chatvector-ai/chatvector-ai?style=social)](https://github.com/chatvector-ai/chatvector-ai)

---

## 🔗 Quick Links

[![Good First Issues](https://img.shields.io/badge/Good%20First%20Issues-Start%20Here-brightgreen?style=for-the-badge&logo=github)](https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22) [![Roadmap](https://img.shields.io/badge/Roadmap-Project%20Plan-1f6feb?style=for-the-badge&logo=bookstack&logoColor=white)](ROADMAP.md) [![Quick Setup](https://img.shields.io/badge/Quick%20Setup-5%20Min-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#-quick-start) [![Project Board](https://img.shields.io/badge/Project%20Board-Track%20Progress-6f42c1?style=for-the-badge&logo=github&logoColor=white)](https://github.com/orgs/chatvector-ai/projects/2) [![Dev Notes](https://img.shields.io/badge/Dev%20Notes-Maintainer%20Guide-6e7781?style=for-the-badge&logo=markdown&logoColor=white)](DEVELOPMENT.md) [![Architecture](https://img.shields.io/badge/Architecture-Overview-purple?style=for-the-badge&logo=markdown&logoColor=white)](ARCHITECTURE.md) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge&logo=markdown&logoColor=white)](https://opensource.org/license/mit) [![Contributing Docs](https://img.shields.io/badge/Contributing%20Docs-Read%20Guide-0E8A16?style=for-the-badge&logo=bookstack&logoColor=white)](CONTRIBUTING.md) [![Contributing Video](https://img.shields.io/badge/Contributing%20Video-Watch-F24E1E?style=for-the-badge&logo=loom&logoColor=white)](https://www.loom.com/share/c41bdbff541f47d49efcb48920cba382) [![Discussions](https://img.shields.io/badge/Discussions-Ask%20%26%20Share-2da44e?style=for-the-badge&logo=github&logoColor=white)](https://github.com/chatvector-ai/chatvector-ai/discussions/51)

---

## 📌 Table of Contents

- [What is ChatVector?](#-what-is-chatvector)
- [ChatVector vs Frameworks](#chatvector-vs-frameworks)
- [Who is this for?](#-who-is-this-for)
- [Current Status](#-current-status)
- [Architecture Overview](#-architecture-overview)
- [Quick Start](#-quick-start)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🔎 What is ChatVector?

ChatVector provides a **clean, extensible backend foundation for RAG-based document intelligence**. It handles the full lifecycle of document Q&A:

- Document ingestion (PDF, text) with configurable chunking strategies
- Text extraction, cleaning, and semantic chunking
- Vector embedding and storage via pgvector
- Semantic retrieval with optional query transformations
- LLM-powered answer generation with cited responses
- Background processing queue with rate limiting and retry logic

The goal is to offer a **developer-focused RAG engine** you can deploy as a service and integrate via HTTP — not a polished end-user SaaS, and not a framework you have to assemble yourself.

---

## ChatVector vs Frameworks

ChatVector is designed as a **production-ready backend service**, not a general-purpose framework. Here's how it compares:

| Aspect | **ChatVector (This Project)** | **General AI Framework (e.g., LangChain)** |
| :--- | :--- | :--- |
| **Primary Goal** | Deliver a **deployable backend service** for document intelligence. | Provide **modular components** to build a wide variety of AI applications. |
| **Out-of-the-Box Experience** | A fully functional FastAPI service with logging, testing, rate limiting, and a clean API. | A collection of tools and abstractions you must wire together and productionize. |
| **Architecture** | **Batteries-included, opinionated engine.** Get a working system for one use case. | **Modular building blocks.** Assemble and customize components for many use cases. |
| **Best For** | Developers, startups, or teams who need a **document Q&A API now** and want to focus on their application layer. | Developers and researchers building novel, complex AI agents or exploring multiple LLM patterns from the ground up. |
| **Path to Production** | **Short.** Configure, deploy, and integrate via API. Built-in observability, rate limiting, and scaling patterns. | **Long.** Requires significant additional work on API layers, monitoring, deployment, and performance tuning. |

---

## 👥 Who is this for?

ChatVector is designed for:

- **Developers** building document intelligence tools or internal knowledge systems
- **Backend engineers** who want a solid RAG foundation without heavy abstractions
- **AI/ML practitioners** experimenting with chunking, retrieval, and prompt strategies
- **Open-source contributors** interested in retrieval systems, embeddings, and LLM orchestration

---

## 🚀 Current Status

### Phases 1–2.5 Complete | Phase 3 Mostly Shipped

Phases 1, 2, and 2.5 are complete. Phase 3 platform work is largely shipped — API-key authentication, tenant isolation, Python SDK parity, hybrid retrieval, and the expanded frontend demo are in place. Remaining Phase 3 work is focused on ecosystem (Node/TypeScript SDK), distributed rate-limit storage, and frontend chat SSE streaming. See [ROADMAP.md](ROADMAP.md) for the full breakdown.

**What's working today:**

**Backend**
- ✅ PDF and text document ingestion
- ✅ Configurable chunking strategies (fixed, paragraph, semantic)
- ✅ Vector embeddings + semantic search via pgvector
- ✅ PostgreSQL/pgvector via SQLAlchemy in all environments (`DATABASE_URL`)
- ✅ Hybrid retrieval (PostgreSQL full-text + vector, RRF fusion)
- ✅ Baseline retrieval reranking (similarity + lexical overlap)
- ✅ Session-scoped and tenant-wide retrieval modes
- ✅ LLM-powered answers with source citations, relevance scores, and score types
- ✅ Query transformations (rewrite, expand, stepback) with session-history context
- ✅ Configurable response personas and system prompt
- ✅ Session-based chat with persisted conversation history
- ✅ SSE streaming chat (`/chat/stream`) with structured `complete` events (citations, `latency_ms`, `model`)
- ✅ Background ingestion queue with rate limiting, retry, and DLQ
- ✅ Redis-backed ingestion queue (production default; in-memory fallback for local dev)
- ✅ Bearer API-key authentication and strict tenant isolation in production
- ✅ Per-tenant rate limiting on authenticated API routes
- ✅ Development/test auth bypass with automatic `DEV_TENANT_ID` bootstrap
- ✅ Structured logging with request ID tracing
- ✅ Health checks with TTL caching on `/status`
- ✅ Security headers, CORS hardening, input validation
- ✅ Production Compose config + GitHub Actions CI
- ✅ Pluggable LLM providers (Gemini, OpenAI, Ollama, Anthropic Claude)
- ✅ Pluggable embedding providers (Gemini, OpenAI, Ollama, Voyage AI)
- ✅ Mixed-provider configurations (e.g. Claude + Voyage)
- ✅ Response metadata: `latency_ms` and `model` on chat and batch responses
- ✅ Python client SDK (upload, status, chat, batch, sessions, streaming, retrieval scopes)

**Frontend Demo**
- ✅ Document upload with live pipeline stage display and ingestion SSE progress
- ✅ RAG chat with source citations, retrieval controls, and retrieval inspector
- ✅ Batch compare and batch synthesize demos
- ✅ Live system status page
- ✅ Structured API error display and grouped Demo/Docs navigation
- ✅ Session sidebar (client-side) and responsive design with dark/light theme
- 🚧 Real-time chat SSE streaming in the demo UI (backend `/chat/stream` is ready; demo uses `POST /chat` with simulated typing in `MessageList.tsx`)

**Active Phase 3 work:**
- 🚧 Node.js/TypeScript SDK (planned)
- 🚧 Redis-backed distributed rate-limit storage across workers
- 🚧 Durable Postgres-backed session metadata (messages persisted; session registry is in-memory)
- 🚧 Frontend demo chat SSE streaming wired to `/chat/stream`
- 🚧 API-key lifecycle tooling beyond CLI create (rotation, expiration)

---

## 🧠 Architecture Overview

### Backend Layer (Core)

- **FastAPI** — modern Python API framework
- **Uvicorn** — high-performance ASGI server
- **slowapi** — per-tenant rate limiting
- **Design goals:** clarity, extensibility, resilience, and security by default

### AI & Retrieval Layer

- **Pluggable providers** — Gemini, OpenAI, Ollama, Anthropic Claude (LLM), and Voyage AI (embeddings); mix and match independently
- **Hybrid retrieval** — vector similarity + PostgreSQL full-text search with RRF fusion
- **Baseline reranking** — deterministic similarity + lexical overlap reranker
- **Retrieval scopes** — session-scoped (default) or tenant-wide search
- **Configurable chunking** — fixed, paragraph, or semantic strategies
- **Query transformations** — rewrite, expand, or stepback before retrieval
- **Response personas** — `default`, `concise`, `conversational`, `academic`, `technical`

### Data Layer

- **PostgreSQL + pgvector** — vector similarity search via SQLAlchemy in all environments
- `DATABASE_URL` controls the target database — local Docker, Neon, RDS, Cloud SQL, Supabase Postgres, etc.
- **Strategy pattern** — DB operations isolated behind a factory; business logic is database-agnostic

### Reference Frontend (Non-Core)

- **Next.js + TypeScript**
- Full end-to-end demo — upload, ingest, chat, citations
- Not production-ready — exists to demonstrate and test backend capabilities

See [ARCHITECTURE.md](ARCHITECTURE.md) for full system design details.

---

## 🎯 Quick Start

After installing Docker and Node.js, start the complete ChatVector development environment with one command.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose (`docker compose`)
- [Node.js](https://nodejs.org/) and npm
- Either:
  - an API key for a supported hosted provider (Gemini or OpenAI), or
  - a local [Ollama](https://ollama.com/) installation

Gemini is the recommended default and the simplest guided setup.

### One-command setup

```bash
make quickstart
```

The command creates the env file, pauses while you add provider credentials, then continues after you press Enter. It installs frontend dependencies, builds the backend Docker image, starts backend services and the non-containerized frontend demo, waits for both to become ready, and opens the frontend and API docs when supported.

Setup is safe to rerun — existing `backend/.env` and `frontend-demo/.env.local` files are never overwritten.

If provider configuration is already complete, `make quickstart` continues immediately without pausing.

### Provider configuration

Edit `backend/.env` to choose providers and set credentials. Gemini is the recommended default:

```bash
LLM_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GEN_AI_KEY=your_google_ai_studio_api_key
```

Supported combinations include Gemini, OpenAI, Ollama, Anthropic Claude (generation), and Voyage AI (embeddings), including mixed setups (for example Claude + Voyage). See `backend/.env.example` for all variables.

### URLs

- Frontend demo (non-core reference UI): http://localhost:3000
- Swagger UI: http://localhost:8000/docs

### Alternative non-interactive flow

```bash
make setup
# edit backend/.env
make
```

- `make setup` — create env files, install dependencies, and build Docker images (prints editing instructions if configuration is incomplete; does not wait)
- `make` — start backend and frontend, then open browser tabs

### Returning contributors

Returning contributors normally use:

```bash
make
```

### Start without browser tabs

```bash
make dev
```

Useful for SSH sessions, CI, or when you prefer to open URLs yourself.

### Useful commands

| Command | Purpose |
|---|---|
| `make quickstart` | Create env, pause for credentials, then start everything |
| `make setup` | Create env files, install dependencies, and build Docker images |
| `make` | Start backend + frontend, open browser tabs (default) |
| `make dev` | Start backend + frontend without opening tabs |
| `make backend` | Start only the backend Docker stack |
| `make frontend` | Start only the frontend demo |
| `make open` | Open the frontend and API docs URLs |
| `make stop` | Stop this repo's frontend process and Docker services |
| `make help` | Show all Make commands |

**Notes:**

- Setup is safe to rerun and preserves existing env files.
- Provider credentials are edited in `backend/.env` — the setup scripts do not prompt for or read API keys in the terminal.
- Press **Ctrl+C** while `make`, `make dev`, or `make quickstart` is running to stop the frontend; backend containers keep running until you run `make stop`.
- The frontend demo is a **non-core, non-containerized** reference UI for testing the backend.

### Try the API

1. `POST /upload` — upload a PDF, get a `document_id` and `status_endpoint`
2. `GET /documents/{document_id}/status` — poll ingestion stage and progress
3. `POST /chat` — ask questions using the `document_id`

---

### Extra Docker Commands

| Command | Purpose |
|---|---|
| `docker compose up` | Start containers without rebuilding |
| `docker compose down` | Stop containers, preserve data |
| `docker compose down -v` | Stop containers and delete all DB data |
| `docker compose up --build` | Rebuild containers after code changes |
| `docker compose logs -f api` | Follow API logs in real time |
| `docker compose exec db psql -U postgres` | Connect to Postgres directly |

Or use the Makefile shortcuts above — run `make help` for the full list.

---

### Manual setup (alternative)

If you prefer not to use Make, copy `backend/.env.example` to `backend/.env` and configure your providers. Gemini is the simplest default:

```env
LLM_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GEN_AI_KEY=your_key_here
```

See `backend/.env.example` for OpenAI, Ollama, Anthropic Claude, Voyage AI, and mixed-provider configurations. Then:

```bash
docker compose up --build

cd frontend-demo
npm ci
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Frontend runs at http://localhost:3000

---

### Python SDK

A synchronous Python client covers upload, status polling, non-streaming and streaming chat, batch chat, session management, and retrieval scope options. A Node.js/TypeScript SDK is planned for Phase 3.

```bash
pip install ./sdk/python
```
```python
from chatvector import ChatVectorClient

with ChatVectorClient("http://localhost:8000", api_key="cv_live_...") as client:
    doc = client.upload_document("report.pdf")
    client.wait_for_ready(doc.document_id, timeout=90)

    session = client.create_session()
    answer = client.chat(
        "What are the key findings?",
        doc.document_id,
        session_id=session.id,
        scope="session",
    )
    print(answer.answer, answer.latency_ms, answer.model)
    for source in answer.sources:
        print(source.file_name, source.page_number, source.score, source.score_type)

    for event in client.stream_chat("Summarize in one paragraph.", doc.document_id, session_id=session.id):
        if event.type == "token":
            print(event.content, end="")
        elif event.type == "complete":
            print(event.latency_ms, event.model, len(event.sources))
```

In development (`APP_ENV=development`), the `api_key` parameter can be omitted — the backend bypasses authentication and attributes requests to `DEV_TENANT_ID`.

See [sdk/python/README.md](sdk/python/README.md) for authentication, error handling, and runnable examples.

---

## 🤝 Contributing

High-impact contribution areas:

- Ingestion & indexing pipelines
- Retrieval quality & evaluation
- Chunking and query transformation strategies
- API design & refactoring
- Performance & scaling
- Security hardening
- SDK development
- Documentation & examples

Frontend contributions are welcome but considered **non-core**.

Pick an open issue and start working — no permission or assignment needed. See
[CONTRIBUTING.md](CONTRIBUTING.md) for details and
[Good First Issues](https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)
to get started.

---

## 📄 License

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/chatvector-ai/chatvector-ai/blob/main/LICENSE)
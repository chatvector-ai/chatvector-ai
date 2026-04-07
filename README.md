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

[![Good First Issues](https://img.shields.io/badge/Good%20First%20Issues-Start%20Here-brightgreen?style=for-the-badge&logo=github)](https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22) [![Roadmap](https://img.shields.io/badge/Roadmap-Project%20Plan-1f6feb?style=for-the-badge&logo=bookstack&logoColor=white)](ROADMAP.md) [![Quick Setup](https://img.shields.io/badge/Quick%20Setup-5%20Min-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#backend-setup) [![Project Board](https://img.shields.io/badge/Project%20Board-Track%20Progress-6f42c1?style=for-the-badge&logo=github&logoColor=white)](https://github.com/orgs/chatvector-ai/projects/2) [![Dev Notes](https://img.shields.io/badge/Dev%20Notes-Maintainer%20Guide-6e7781?style=for-the-badge&logo=markdown&logoColor=white)](DEVELOPMENT.md) [![Architecture](https://img.shields.io/badge/Architecture-Overview-purple?style=for-the-badge&logo=markdown&logoColor=white)](ARCHITECTURE.md) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge&logo=markdown&logoColor=white)](https://opensource.org/license/mit) [![Contributing Docs](https://img.shields.io/badge/Contributing%20Docs-Read%20Guide-0E8A16?style=for-the-badge&logo=bookstack&logoColor=white)](CONTRIBUTING.md) [![Contributing Video](https://img.shields.io/badge/Contributing%20Video-Watch-F24E1E?style=for-the-badge&logo=loom&logoColor=white)](https://www.loom.com/share/c41bdbff541f47d49efcb48920cba382) [![Discussions](https://img.shields.io/badge/Discussions-Ask%20%26%20Share-2da44e?style=for-the-badge&logo=github&logoColor=white)](https://github.com/chatvector-ai/chatvector-ai/discussions/51)

---

## 📌 Table of Contents

- [What is ChatVector?](#-what-is-chatvector)
- [ChatVector vs Frameworks](#chatvector-vs-frameworks)
- [Who is this for?](#-who-is-this-for)
- [Current Status](#-current-status)
- [Architecture Overview](#-architecture-overview)
- [Quick Start](#-quick-start-run-in-5-minutes)
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

### Phase 2 — Largely Complete

The core RAG backend and frontend demo are fully functional. Phase 2 focused on developer experience, retrieval quality, and production hardening.

**What's working today:**

**Backend**
- ✅ PDF and text document ingestion
- ✅ Configurable chunking strategies (fixed, paragraph, semantic)
- ✅ Vector embeddings + semantic search via pgvector
- ✅ LLM-powered answers with source citations
- ✅ Query transformations (rewrite, expand, stepback)
- ✅ Configurable system prompt and LLM parameters
- ✅ Background ingestion queue with rate limiting, retry, and DLQ
- ✅ Structured logging with request ID tracing
- ✅ Health checks with TTL caching on /status
- ✅ Per-IP rate limiting on all public endpoints
- ✅ Security headers, CORS hardening, input validation
- ✅ Production Compose config + GitHub Actions CI
- ✅ Python client SDK

**Frontend Demo**
- ✅ Document upload with live pipeline stage display
- ✅ Real-time ingestion status polling
- ✅ Full RAG chat with source citations
- ✅ Responsive design with dark developer aesthetic

**In progress / Phase 3:**
- 🚧 Redis-backed durable ingestion queue (#123)
- 🚧 Pluggable LLM & embedding providers (Gemini, OpenAI, Ollama)
- 🚧 Authentication & multi-tenancy
- 🚧 Streaming LLM responses

---

## 🧠 Architecture Overview

### Backend Layer (Core)

- **FastAPI** — modern Python API framework
- **Uvicorn** — high-performance ASGI server
- **slowapi** — per-IP rate limiting
- **Design goals:** clarity, extensibility, resilience, and security by default

### AI & Retrieval Layer

- **Google Gemini** — LLM generation + embeddings (pluggable providers planned)
- **Configurable chunking** — fixed, paragraph, or semantic strategies
- **Query transformations** — rewrite, expand, or stepback before retrieval
- **Prompt configuration** — externalized system prompt and LLM parameters

### Data Layer

- **PostgreSQL + pgvector** — vector similarity search
- **SQLAlchemy** (development) / **Supabase** (production)
- **Strategy pattern** — swap backends without touching business logic

### Reference Frontend (Non-Core)

- **Next.js + TypeScript**
- Full end-to-end demo — upload, ingest, chat, citations
- Not production-ready — exists to demonstrate and test backend capabilities

See [ARCHITECTURE.md](ARCHITECTURE.md) for full system design details.

---

## 🎯 Quick Start: Run in 5 Minutes

### Prerequisites

- Docker & Docker Compose — [Install Docker](https://docs.docker.com/get-docker/)
- Google AI Studio API Key — [Get Key](https://aistudio.google.com/)

### Backend Setup

**1. Create `backend/.env`:**
```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and set your API key:
```env
APP_ENV=development
LOG_LEVEL=INFO
GEN_AI_KEY=your_google_ai_studio_api_key_here
MAX_UPLOAD_SIZE_MB=10
```

**2. Start the stack:**
```bash
docker compose up --build
```

This starts Postgres with pgvector and the API with live reload.

**3. Test the API:**

- Root: http://localhost:8000
- Swagger UI: http://localhost:8000/docs

**Try the endpoints:**

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

Or use the Makefile shortcuts — run `make help` to see all available commands.

---

### Frontend Demo (Non-Core)
```bash
cd frontend-demo
npm install

# Create frontend env
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

npm run dev
```

Frontend runs at http://localhost:3000

Or start backend + frontend together:
```bash
make dev
```

---

### Python SDK
```bash
pip install ./sdk/python
```
```python
from chatvector import ChatVectorClient

with ChatVectorClient("http://localhost:8000") as client:
    doc = client.upload_document("report.pdf")
    client.wait_for_ready(doc.document_id, timeout=90)
    answer = client.chat("What are the key findings?", doc.document_id)
    print(answer.answer)
    for source in answer.sources:
        print(source.file_name, source.page_number)
```

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for details and
[Good First Issues](https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)
to get started.

---

## 📄 License

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/chatvector-ai/chatvector-ai/blob/main/LICENSE)
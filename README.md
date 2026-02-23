# ChatVector-AI

### Open-Source Backend-First RAG Engine for Document Intelligence

ChatVector-AI is an open-source Retrieval-Augmented Generation (RAG) engine for ingesting, indexing, and querying unstructured documents such as PDFs and text files.

Think of it as an engine developers can use to build document-aware applications — such as research assistants, contract analysis tools, or internal knowledge systems — without having to reinvent the RAG pipeline.

<p>
  <img src="https://img.shields.io/badge/Status-Backend%20MVP-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/PRs-Welcome-brightgreen" alt="PRs Welcome">
  <img src="https://img.shields.io/badge/Python-FastAPI-blue" alt="Python FastAPI">
  <img src="https://img.shields.io/badge/AI-RAG%20Engine-orange" alt="AI RAG">
</p>

---

⭐ **Star the repo to follow progress and support the project!**

[![GitHub stars](https://img.shields.io/github/stars/chatvector-ai/chatvector-ai?style=social)](https://github.com/chatvector-ai/chatvector-ai)
**Next Milestone:** 25

```
██████████████░░░░░░░░░░░░░░░░ 12/25 stars
```

---

## 🔗 Quick Links

- [![Good First Issues](https://img.shields.io/badge/Good%20First%20Issues-Start%20Here-brightgreen?style=for-the-badge&logo=github)](https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22) - Start here if new to the project
- [![Roadmap](https://img.shields.io/badge/Roadmap-Project%20Plan-1f6feb?style=for-the-badge&logo=bookstack&logoColor=white)](ROADMAP.md) - Long-term vision + Issue details
- [![Quick Setup](https://img.shields.io/badge/Quick%20Setup-5%20Min-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#backend-setup) - Get running locally in 5 min (Docker + PostgreSQL)
- [![Project Board](https://img.shields.io/badge/Project%20Board-Track%20Progress-6f42c1?style=for-the-badge&logo=github&logoColor=white)](https://github.com/orgs/chatvector-ai/projects/2) - Track development progress & priorities
- [![Demo Video](https://img.shields.io/badge/Demo%20Video-3%20Min-625DF5?style=for-the-badge&logo=loom&logoColor=white)](https://www.loom.com/share/b7be8b165031450aad650144a71c1a10) - 3-min overview of ChatVector-AI in action
- [![Contributing Docs](https://img.shields.io/badge/Contributing%20Docs-Read%20Guide-0E8A16?style=for-the-badge&logo=bookstack&logoColor=white)](CONTRIBUTING.md) [![Contributing Video](https://img.shields.io/badge/Contributing%20Video-Watch-F24E1E?style=for-the-badge&logo=loom&logoColor=white)](https://www.loom.com/share/c41bdbff541f47d49efcb48920cba382) - PR workflow & code standards
- [![Discussions](https://img.shields.io/badge/Discussions-Ask%20%26%20Share-2da44e?style=for-the-badge&logo=github&logoColor=white)](https://github.com/chatvector-ai/chatvector-ai/discussions/51) - Community hub for questions & ideas
- [![Dev Notes](https://img.shields.io/badge/Dev%20Notes-Maintainer%20Guide-6e7781?style=for-the-badge&logo=markdown&logoColor=white)](DEVELOPMENT.md) - Internal maintainer notes & conventions

---

## 📌 Table of Contents

- [What is ChatVector-AI?](#-what-is-chatvector-ai)
- [ChatVector-AI vs Frameworks](#chatvector-vs-frameworks)
- [Who is this for?](#-who-is-this-for)
- [Current Status](#-current-status)
- [Architecture Overview](#-architecture-overview)
  - [Backend Layer (Core)](#backend-layer-core)
  - [AI & Retrieval Layer](#ai--retrieval-layer)
  - [Data Layer](#data-layer)
  - [Reference Frontend (Non-Core)](#reference-frontend-non-core)
- [Quick Start: Run in 5 Minutes](#-quick-start-run-in-5-minutes)
  - [Backend Setup](#backend-setup)
  - [Frontend-demo Setup](#frontend-layer-non-core)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🔎 What is ChatVector-AI?

ChatVector-AI provides a **clean, extensible backend foundation for RAG-based document intelligence**. It handles the full lifecycle of document Q&A:

- Document ingestion (PDF, text)
- Text extraction and chunking
- Vector embedding and storage
- Semantic retrieval
- LLM-powered answer generation

The goal is to offer a **developer-focused RAG engine** that can be embedded into other applications, tools, or products — not a polished end-user SaaS.

---

## ChatVector vs Frameworks

ChatVector-AI is designed as a **production-ready backend engine**, not a general-purpose framework. If you need a running, reliable API for document Q&A, this project provides a complete, opinionated solution. Here's how it compares to the approach of using a modular framework:

| Aspect                        | **ChatVector-AI (This Project)**                                                                                 | **General AI Framework (e.g., LangChain)**                                                                          |
| :---------------------------- | :--------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------ |
| **Primary Goal**              | Deliver a **deployable backend service** for document intelligence.                                              | Provide **modular components** to build a wide variety of AI applications.                                          |
| **Out-of-the-Box Experience** | A fully functional FastAPI service with logging, testing, and a clean API.                                       | A collection of tools and abstractions you must wire together and productionize.                                    |
| **Architecture**              | **Batteries-included, opinionated engine.** Get a working system for one use case.                               | **Modular building blocks.** Assemble and customize components for many use cases.                                  |
| **Best For**                  | Developers, startups, or teams who need a **document Q&A API now** and want to focus on their application layer. | Developers and researchers building novel, complex AI agents or exploring multiple LLM patterns from the ground up. |
| **Path to Production**        | **Short.** Configure, deploy, and integrate via API. Built-in observability and scaling patterns.                | **Long.** Requires significant additional work on API layers, monitoring, deployment, and performance tuning.       |

---

## 👥 Who is this for?

ChatVector-AI is designed for:

- **Developers** building document intelligence tools or internal knowledge systems
- **Backend engineers** who want a solid RAG foundation without heavy abstractions
- **AI/ML practitioners** experimenting with chunking, retrieval, and prompt strategies
- **Open-source contributors** interested in retrieval systems, embeddings, and LLM orchestration

---

## 🚀 Current Status

### Backend MVP (Core Engine)

The core RAG backend is **complete and functional**.

**What works today:**

- ✅ PDF text extraction
- ✅ Basic chunking pipeline
- ✅ Vector embeddings
- ✅ Semantic search (pgvector)
- ✅ LLM-powered answers
- ✅ Supabase integration

**Backend improvements in progress:**

- 🚧 Advanced chunking strategies
- 🚧 Error handling & logging
- 🚧 API rate limiting
- 🚧 Performance optimization
- 🚧 Authentication & access control

Frontend Demo: A lightweight UI for testing the backend API. Not production-ready.

---

## 🧠 Architecture Overview

### Backend Layer (Core)

- **FastAPI** — modern Python API framework with automatic OpenAPI docs
- **Uvicorn** — high-performance ASGI server
- **Design goals:** clarity, extensibility, and debuggability

### AI & Retrieval Layer

- **Google AI Studio (Gemini)** — LLM + embeddings
- **Features:** chunking, semantic retrieval, prompt construction

### Data Layer

- **Supabase** — PostgreSQL backend
- **pgvector** — native vector similarity search
- **Storage:** document metadata and embeddings

### Reference Frontend (Non-Core)

- **Next.js + TypeScript**
- Exists solely to demonstrate backend usage
- Not production-ready
- Subject to breaking changes

---

## 🎯 Quick Start: Run in 5 Minutes

## Backend Setup

Follow these steps to get the backend running in under 5 minutes.

### Prerequisites

- Docker & Docker Compose installed
  - [Install Docker](https://docs.docker.com/get-docker/) (Mac/Windows/Linux)

- Google AI Studio API Key ([Get Key](https://aistudio.google.com/))

### Setup `.env`

```bash
cd backend

# Create .env file
Create .env file in /backend and paste in the following values

APP_ENV=development
LOG_LEVEL=INFO
LOG_USE_UTC=false
GEN_AI_KEY=your_google_ai_studio_api_key_here
# Replace GEN_AI_KEY with your actual API key
```

### Launch Backend

Note: Make sure Docker Desktop is running (Mac/Windows) before executing this command.

Run from the project root (where `docker-compose.yml` is located):

```bash
docker-compose up --build
```

**What happens:**

- Postgres with pgvector starts automatically and initializes tables + vector functions
- API waits for Postgres healthcheck
- Live reload enabled for backend code

### Test the API

- Root: [http://localhost:8000](http://localhost:8000)
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)

**Try endpoints:**

1. `/upload` - Upload a PDF and get a `document_id` and `status_endpoint`
2. `/documents/{document_id}/status` - Poll upload stage/progress metadata
3. `/chat` - Ask questions using the `document_id`

---

## 2️⃣ Extra Docker Commands

| Command                                   | Purpose                                                                       |
| ----------------------------------------- | ----------------------------------------------------------------------------- | --- |
| `docker-compose up`                       | Start containers (without rebuilding - normal start)                          |
| `docker-compose down`                     | Stop containers (preserve data -- normal stop)                                |
| `docker-compose down -v`                  | Stop containers **and delete all database data**. Use to reset DB completely. |
| `docker-compose up --build`               | Rebuild containers after code changes or DB reset.                            |     |
| `docker-compose logs -f api`              | Follow API logs in real time.                                                 |
| `docker-compose exec db psql -U postgres` | Connect to Postgres inside Docker for manual queries.                         |

---

## 3️⃣ Run Python Scripts Outside Docker (Optional / Advanced)

If you want to run scripts or the API **without Docker**:

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate   # Mac/Linux
venv\Scripts\activate      # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set DATABASE_URL in .env if different from Docker
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres

# 4. Run scripts or start API manually
python scripts/your_script.py
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Notes:**

- Requires a running Postgres instance with pgvector enabled
- Only needed for local development outside Docker

---

✅ **Result**

- Docker-first setup is simple, cross-platform, and fully initialized
- Optional sections give control for resets, logs, or running scripts manually

---

## Frontend Layer (Non-Core)

Note: The frontend serves as the web presence for the OSS, and as a testing demo -- but is not central to the actual OSS.

<h4>Prerequisites</h4>
<ul>
  <li>Node.js 18+</li>
  <li>npm or yarn</li>
</ul>

<h4>Setup Instructions</h4>

```bash
# 1. Navigate to frontend directory
cd frontend-demo

# 2. Install dependencies
npm install

# 3. Start development server
npm run dev

#4. Run in browser
The frontend will run on http://localhost:3000
```

---

## 🤝 Contributing

High-impact contribution areas:

- Ingestion & indexing pipelines
- Retrieval quality & evaluation
- Chunking strategies
- API design & refactoring
- Performance & scaling
- Documentation & examples

Frontend contributions are welcome but considered **non-core**.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 📄 License

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/chatvector-ai/chatvector-ai/blob/main/LICENSE)

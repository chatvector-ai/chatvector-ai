# ChatVector Development Roadmap

This document outlines the current development focus and future direction of the ChatVector project. It is intended for contributors to quickly understand priorities and pick up tasks.

---

## ✅ Phase 1 — Core Engine Stabilization (Complete)

Phase 1 focused on building and hardening the foundational RAG pipeline.

**Delivered**

- Document ingestion pipeline (PDF, text)
- Chunking strategies (fixed, paragraph)
- Embedding + vector storage via pgvector
- Retrieval + LLM answer generation with source citations
- Centralized retry utility with backoff
- Background ingestion queue
- Advanced logging and request ID middleware
- `/status` endpoint with live system metrics
- JSON-based `POST /chat` API
- LLM error handling with distinct error classification
- Upload pipeline refactored into dedicated service layer

**Outcome:** A stable, production-capable stateless RAG backend engine.

---

## ✅ Phase 2 — Capability Expansion & Developer Experience (Complete)

Phase 2 expanded flexibility, retrieval quality, and usability while maintaining backend-first design.

**Backend**

- Advanced chunking strategies (fixed, paragraph, semantic)
- Query transformations (rewrite, expand, stepback)
- Prompt tuning and system prompt configuration
- Pluggable LLM and embedding providers (Gemini, OpenAI, Ollama)
- Per-tenant rate limiting via slowapi (replaces earlier per-IP limiting)
- LLM + embedding health checks on `/status`
- Observability improvements and structured logging guide
- Production Docker Compose and GitHub Actions CI pipeline
- Security hardening (headers, CORS, upload validation, error handling)
- Python client SDK with typed models and retry handling
- Redis-backed ingestion queue (promoted to the production default during Phase 3A; the in-memory queue remains available for local development)

**Frontend Demo**

- End-to-end RAG chat interface
- Document upload + ingestion status tracking
- Source citations display
- Typing effect, light/dark theme toggle
- Responsive navbar and homepage redesign

**Outcome:** A flexible, developer-friendly RAG backend with strong defaults and a working demo.

---

## ✅ Phase 2.5 — Hardening & Consistency Layer (Complete)

A focused stabilization pass based on a backend audit conducted ahead of Phase 3.

**Delivered**

- Unified API error contract across `/chat` and `/chat/batch`
- Provider timeout standardization (LLM + embeddings)
- Embedding validation — no silent dimension fallbacks
- Logging safety improvements — no sensitive payload leakage
- Queue consistency improvements and documentation alignment
- Atomic document deletion via SQLAlchemy ORM transactions
- Expanded test coverage for core flows
- Config and `.env` alignment with runtime behavior

**Outcome:** A production-ready, internally consistent backend ready for architectural expansion.

---

## 🚧 Phase 3 — Platform Evolution (Mostly Shipped)

### North Star

Transform ChatVector into a **multi-tenant, session-aware document intelligence backend** while preserving a simple, plug-and-play developer experience.

**Core Principle:** Simple by default, powerful when explicitly enabled.

> **Current status:** Phase 3A and 3B backend platform work is largely complete — API-key authentication, tenant isolation, sessions, streaming, hybrid retrieval, Python SDK parity, and the expanded frontend demo are shipped. Remaining work is ecosystem expansion (Node/TypeScript SDK), distributed rate-limit storage, frontend chat SSE wiring, and API-key lifecycle tooling.

---

### Phase 3A — Core Platform Foundation

This phase introduces the primary architectural shift. Phase 3B and 3C work builds on this foundation.

#### ✅ Completed

**Session-based chat (document-scoped)**

- Sessions provide conversation memory and document query scope
- Auto-created if no `session_id` is provided — zero config required
- Sessions bound to documents as they are queried
- Full message history persisted per session (user and assistant turns)
- Explicit session management endpoints: create, list, get, delete
- Frontend anonymous sessions and session sidebar

> **Session durability note:** `chat_messages` rows are persisted to PostgreSQL and survive restarts. Session metadata — including `document_ids` bound to a session — is held in an in-memory registry (`session_service._SESSIONS`) and is **not** durable across process restarts or shared across API workers. Chat history remains available after restart, but session-scoped document bindings may be lost until sessions are recreated.

**Context injection for answer generation**

- Recent conversation history loaded into the LLM context window
- Retrieval operates on a clean, transformed query — not raw history
- LLM receives: top-k retrieved chunks + a bounded recent message window
- Prevents token explosion and retrieval quality degradation over long sessions

**Query transformation with session history**

- When `QUERY_TRANSFORMATION_ENABLED=true`, rewrite/expand/stepback strategies receive a bounded window of recent session messages
- History informs both query transformation and answer-generation context

**Streaming LLM responses**

- SSE endpoint at `/chat/stream` for provider token streaming
- Structured final `complete` event with citations, `latency_ms`, and `model`
- Session messages persisted after stream completes
- Ingestion progress over SSE with persistent pipeline UI in the frontend demo

**API authentication & multi-tenancy**

- Bearer API-key parsing and validation (`Authorization: Bearer <API_KEY>`)
- Secure API-key storage, lookup, and API key → tenant resolution
- Rejection of missing or invalid keys in production
- Strict tenant scoping on documents, sessions, chunks, ingestion jobs, and delete operations
- Per-tenant rate limiting on authenticated API routes (in-memory `slowapi`; Redis-backed storage deferred)
- Development/test auth bypass with automatic `DEV_TENANT_ID` tenant bootstrap on startup
- Production tenant/key creation via `python -m backend.cli create-tenant-key`

**Redis queue as production default**

- Redis-backed ingestion queue promoted to default in production environments (`APP_ENV=production`)
- In-memory queue retained as development fallback
- Documentation and configuration aligned

**Database backend standardization**

- Supabase HTTP client/RPC backend removed
- SQLAlchemy/PostgreSQL via `DATABASE_URL` is the only supported database backend in all environments
- Managed/cloud Postgres (Neon, RDS, Cloud SQL, Supabase Postgres via direct connection) supported through standard connection strings

#### ⏳ Remaining

**API-key lifecycle tooling**

- Programmatic rotation, expiration, and revocation workflows beyond CLI create and DB status updates
- Optional `external_user_id` field for developer-side user mapping

**Frontend demo chat SSE**

- Backend `/chat/stream` is ready; the demo chat page still uses non-streaming `POST /chat` with a simulated character-by-character typing animation

**Durable session metadata**

- Postgres-backed session registry and `document_ids` bindings (messages are already persisted; metadata is process-local today)

**Distributed rate limiting**

- Redis-backed rate-limit storage across multiple API workers (current `slowapi` storage is in-memory per process)

---

### Phase 3B — Quality & Ecosystem

Build on the platform foundation to improve response quality and expand developer reach.

#### ✅ Completed

**Hybrid retrieval**

- PostgreSQL full-text search combined with vector similarity
- Reciprocal Rank Fusion (RRF) for result merging
- Configurable via `HYBRID_RETRIEVAL_ENABLED`

**Retrieval reranking**

- Reranker abstraction with a deterministic similarity + lexical-overlap baseline
- Configurable via `ENABLE_RERANKING` and `RERANKER_PROVIDER`
- External cross-encoder or hosted reranking providers remain future enhancements

**Scoped retrieval**

- Default behavior: retrieval scoped to session documents
- Optional `scope: "tenant"` parameter enables search across all tenant documents
- Supported on `/chat`, `/chat/stream`, and `/chat/batch`

```json
{
  "question": "What do we know about pricing?",
  "scope": "tenant"
}
```

**Configurable response personas**

- Predefined system prompt styles: `default`, `concise`, `conversational`, `academic`, `technical`
- Configured via `PROMPT_PERSONA` environment variable
- Clear precedence: custom prompt path > persona > default system prompt

**Additional provider support**

- Anthropic Claude (LLM — non-streaming and streaming generation)
- Voyage AI (embeddings — includes domain-tuned models)
- Mixed-provider configurations (e.g. Claude + Voyage, OpenAI LLM + Voyage embeddings)

**Response and citation metadata**

- Relevance scores and `score_type` on source citations (`vector`, `hybrid_rrf`, `reranked`)
- `latency_ms` and `model` fields on non-streaming `/chat` and `/chat/batch` responses
- Structured streaming `complete` events with the same metadata

**Python SDK**

- Upload, status polling, `wait_for_ready`, non-streaming chat, batch chat
- Session management (`create_session`, `list_sessions`, `delete_session`)
- Streaming chat (`stream_chat`) with typed `token` and `complete` events
- Retrieval scope options (`session` / `tenant`)
- Typed responses, structured errors, relevance scores, model/latency metadata

**Frontend demo improvements**

- Chat with retrieval controls and retrieval inspector
- Batch compare and batch synthesize modes
- Live system status page
- Structured API error display
- Grouped Demo and Docs navigation
- Shared components and loading skeletons
- Ingestion SSE progress (document status stream)

#### ⏳ Remaining

**Node.js / TypeScript SDK**

- First-class SDK for backend developers — planned, not yet implemented
- Typed API client, retry with backoff, `waitForReady()` polling helper
- Session-aware chat support
- Published to npm

**Inspection and observability tooling**

- Query transformation visualization (opt-in debug metadata beyond current `retrieval_debug` payloads)
- Richer per-component retrieval score breakdown (today: collapsed `score` + `score_type` on citations)
- Async Python SDK client
- Ingestion SSE client in Python SDK (document status stream not exposed in SDK)

---

### Phase 3C — Polish & Adoption

Focus on documentation, discoverability, and real-world integration patterns.

#### 10. Documentation Site

- Getting started guide
- API reference generated from OpenAPI schema
- SDK documentation (Python + Node)
- Deployment guides (self-hosted and cloud)

#### 11. Live API Explorer

- Swagger UI or Scalar integration
- Try-it-out functionality for all endpoints
- Enabled in non-production environments only

#### 12. Example Applications

- At least two reference implementations:
  - Node.js backend using the Node SDK
  - Python FastAPI backend using the Python SDK
- Demonstrate real integration patterns, not toy examples

---

## 🔮 Phase 4 — Advanced Capabilities (Future)

These are valuable extensions deferred until the Phase 3 platform foundation is stable.

**Retrieval Quality**

- External cross-encoder or API-based reranking providers (e.g. Cohere Rerank, Jina)
- Retrieval evaluation and benchmarking datasets
- Advanced retrieval observability (component score traces, faithfulness evaluation)

**Scalability & Performance**

- Embedding and query result caching
- Webhook-based ingestion callbacks
- Advanced rate limiting and usage tracking

**Data & Document Management**

- Document versioning
- Retrieval feedback signals (thumbs up/down on answers)
- Multi-format document ingestion (e.g. Docling — DOCX, PPTX, HTML, images)

**Advanced Retrieval**

- Knowledge graph and GraphRAG approaches
- Domain-specific pipelines (legal, academic, code-aware)

**Ecosystem**

- React SDK
- Community showcase and integrations gallery

---

## ❌ Non-Goals

ChatVector is intentionally **not** building the following:

| Item | Reason |
|------|--------|
| User authentication (login/signup) | Developer's responsibility at the application layer |
| Billing or subscriptions | Out of scope for an open-source backend engine |
| Collaborative workspaces | Different product category |
| Admin dashboards | Not needed for a developer tool |
| API-key lifecycle UI (rotation, revocation, user mapping) | CLI and DB updates only; programmatic tooling is roadmap |
| OAuth, RBAC, or per-user login | API-key auth only; application-layer identity is the developer's responsibility |
| Full SaaS product layer | Conflicts with backend-first positioning |
| Elasticsearch dependency | pgvector + PostgreSQL full-text covers the same ground at this scale |

---

## Phase 3 Success Criteria

Progress toward the Phase 3 north star:

- ✅ Stateful document conversations with persisted session memory
- ✅ Streaming chat and ingestion progress (SSE)
- ✅ Structured streaming `complete` events with citations, `latency_ms`, and `model`
- ✅ Hybrid retrieval, baseline reranking, and configurable retrieval scopes
- ✅ Provider flexibility across Gemini, OpenAI, Ollama, Claude, and Voyage embeddings
- ✅ Response personas, citation relevance scores/score types, and response metadata (`latency_ms`, `model`)
- ✅ Bearer API-key authentication and strict tenant isolation in production
- ✅ Python SDK with sessions, streaming, and retrieval scope support
- ✅ SQLAlchemy/PostgreSQL as the only database backend (`DATABASE_URL` in all environments)
- ✅ Frontend demo: chat, batch compare/synthesize, status, retrieval controls, retrieval inspector
- ⏳ Frontend demo chat SSE streaming (backend ready; UI still uses `POST /chat` with simulated typing)
- ⏳ Durable Postgres-backed session metadata (messages persisted; session registry is in-memory)
- ⏳ Node.js/TypeScript SDK planned
- ⏳ Redis-backed distributed rate-limit storage across workers
- ⏳ Documentation site, examples, and advanced inspection tooling in progress

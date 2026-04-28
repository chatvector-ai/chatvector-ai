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
- Per-IP rate limiting via slowapi
- LLM + embedding health checks on `/status`
- Observability improvements and structured logging guide
- Production Docker Compose and GitHub Actions CI pipeline
- Security hardening (headers, CORS, upload validation, error handling)
- Python client SDK with typed models and retry handling
- Redis-backed ingestion queue (implemented, not yet default in production)

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
- Supabase delete atomicity (transaction/RPC-based)
- Expanded test coverage for core flows
- Config and `.env` alignment with runtime behavior

**Outcome:** A production-ready, internally consistent backend ready for architectural expansion.

---

## 🚧 Phase 3 — Platform Evolution (In Progress)

### North Star

Transform ChatVector into a **multi-tenant, session-aware document intelligence backend** while preserving a simple, plug-and-play developer experience.

**Core Principle:** Simple by default, powerful when explicitly enabled.

---

### Phase 3A — Core Platform Foundation

This phase introduces the primary architectural shift. All Phase 3B and 3C work depends on this foundation.

#### 1. API Authentication & Multi-Tenancy

- API key (`Bearer <API_KEY>`) required for all endpoints
- Each API key maps 1:1 to a tenant — implicit and strict
- All resources (documents, sessions, queries, ingestion jobs) automatically scoped to tenant
- Per-tenant rate limiting replaces per-IP limiting
- No user accounts or auth flows — API-level only
- No tenant overrides accepted in request bodies

#### 2. Session-Based Chat (Document-Scoped)

- Sessions provide conversation memory and document query scope
- Auto-created if no `session_id` is provided — zero config required
- Sessions bound to a specific set of documents at creation
- Full message history persisted per session (user and assistant turns)
- Optional `external_user_id` field for developer-side user mapping
- Explicit session management endpoints: create, list, delete

#### 3. Context Injection Strategy

- Conversation history is used to improve query rewriting and expansion
- Retrieval operates on a clean, transformed query — not raw history
- LLM receives: top-k retrieved chunks + a small recent message window
- Prevents token explosion and retrieval quality degradation over long sessions

#### 4. Streaming LLM Responses

- SSE endpoint at `/chat/stream` for token-by-token streaming
- Final structured event includes citations and source metadata
- Session message persisted after stream completes

#### 5. Redis Queue as Production Default

- Redis-backed ingestion queue promoted to default in production environments
- In-memory queue retained as development fallback
- Documentation and configuration aligned

---

### Phase 3B — Quality & Ecosystem

Build on the platform foundation to improve response quality and expand developer reach.

#### 6. Configurable Response Personas

- Predefined system prompt styles: `default`, `conversational`, `academic`, `technical`, `concise`
- Configured via `PROMPT_PERSONA` environment variable
- Clear precedence: custom prompt path > persona > default system prompt
- No pipeline changes required — prompt engineering only

#### 7. Additional Provider Support

- Claude (LLM-only — Anthropic has no embeddings API)
- Voyage AI (embeddings — includes domain-tuned models)
- Explicit support and documentation for mixed-provider setups (e.g. Claude + Voyage)

#### 8. Scoped Retrieval with Optional Tenant-Wide Querying

- Default behavior: retrieval scoped to session documents
- Optional `scope: "tenant"` parameter enables search across all tenant documents
- Opt-in only — clearly documented with cost and latency implications

```json
{
  "question": "What do we know about pricing?",
  "scope": "tenant"
}
```

#### 9. Node.js / TypeScript SDK

- First-class SDK for backend developers
- Typed API client, retry with backoff, `waitForReady()` polling helper
- Session-aware chat support
- Published to npm

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
- Hybrid search (PostgreSQL full-text + vector search — BM25 + pgvector)
- Reranking layer (cross-encoder or API-based, e.g. Cohere Rerank)

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
| Full SaaS product layer | Conflicts with backend-first positioning |
| Elasticsearch dependency | pgvector + PostgreSQL full-text covers the same ground at this scale |

---

## Phase 3 Success Criteria

By the end of Phase 3, ChatVector should be:

- ✅ A secure, multi-tenant RAG API accessed via API key
- ✅ Capable of stateful document conversations with session memory
- ✅ Streaming-first with modern chatbot UX
- ✅ Provider-flexible — mix and match LLMs and embedding models
- ✅ Simple to use by default, powerful when advanced features are enabled
- ✅ Supported by SDKs in Python and Node.js
- ✅ Backed by real example applications and comprehensive documentation

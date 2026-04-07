# ChatVector Development Roadmap

This document outlines the current development focus and future direction of the ChatVector project. It is intended for contributors to quickly understand priorities and pick up tasks.

---

## ✅ Phase 1: Stabilize & Optimize Core Engine (Complete)

Phase 1 focused on hardening the RAG backend for reliability, observability, and performance. All core work is shipped.

**What shipped:**

- Ingestion pipeline robustness and error handling
- Async/batch processing foundations
- Embedding queue for production scaling
- Centralized retry utility
- Advanced logging and request ID middleware
- Chunk metadata, chunk tuning, and source citation support
- Real system metrics on /status endpoint
- Terminology standardized to "ingestion" throughout
- POST /chat migrated to JSON request body
- LLM error handling with distinct error classification
- Upload pipeline refactored into dedicated service layer

---

## ✅ Phase 2: Enhance Developer Experience (Largely Complete)

Phase 2 focused on expanding capabilities, improving retrieval quality, hardening the backend for production, and delivering a working end-to-end frontend demo.

**What shipped:**

**Backend**
- Advanced chunking strategies — fixed, paragraph, and semantic chunking with configurable strategy via env
- Query transformations — rewrite, expand, and stepback strategies between user input and vector search
- Prompt tuning & system prompt configuration — externalized system prompt and LLM parameters
- Python client SDK — lightweight SDK wrapping core API endpoints with typed models and error handling
- Observability — embedding and LLM health checks on /status, structured log shipping guide, access log persistence
- Deployment improvements — production Compose config, GitHub Actions CI pipeline, deployment documentation
- API rate limiting — per-IP rate limiting on all public endpoints via slowapi
- Retry utility hardening — per-attempt timeouts, jitter, 429-aware retries, queue job backoff
- Resilience hardening — LLM HTTP timeouts, SQLAlchemy statement timeout, Supabase client timeouts
- Health check caching — in-memory TTL cache for embedding and LLM health checks on /status
- Security hardening — security headers middleware, CORS tightening, upload filename sanitization, MIME validation, input bounds, error message leakage prevention, docs disabled in production

**Frontend**
- Homepage redesign — sharp, technical landing page with hero, features, pipeline, and developer sections
- Navbar redesign — responsive navbar with mobile drawer, active states, and GitHub CTA
- Chat page — full end-to-end demo: document upload, ingestion status polling, live pipeline stage display, and real RAG-powered chat
- Backend integration — POST /chat wired up with loading state, inline errors, and source citations
- Design system — tokens documented in globals.css, Tailwind conventions established

**Still in progress / open for contributors**
- Redis-backed durable ingestion queue — replace in-memory queue for job durability and multi-worker support

---

## 🏗 Phase 3: Scale & Specialize (Next)

Focus: Production-ready document intelligence platform.

- **Authentication & multi-tenancy** — gate all endpoints including /queue/stats; add tenant model across upload, chat, and queue
- **Pluggable LLM & embedding providers** — support Gemini, OpenAI, and Ollama via env config
- **Streaming LLM responses** — token-by-token streaming via Server-Sent Events
- **Specialized pipelines** — legal, academic, or code document handling
- **Ecosystem growth** — community integrations, example applications
- **Frontend maturity** — full documentation site with live API explorer and community showcase gallery

---

## 📌 Notes

- Issue status (blocked, in progress, etc.) is visible when you click through to GitHub.
- This roadmap provides a quick overview; click any issue for full details.
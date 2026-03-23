# ChatVector-AI Development Roadmap

This document outlines the current development focus and future direction of the ChatVector-AI project. It is intended for contributors to quickly understand priorities and pick up tasks.

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

## 🚀 Phase 2: Enhance Developer Experience (Current)

Focus: Make ChatVector-AI easier to adopt, extend, and integrate.

- **Redis caching** — replaces in-memory queue with a durable, persistent queue and adds embedding/response caching for performance
- **Observability** — LLM and embedding health monitoring on /status; structured log shipping to DataDog, Splunk, or ELK
- **Extended RAG features** — advanced chunking strategies, query transformations, prompt tuning
- **Developer tools** — client SDKs, deployment improvements
- **Frontend expansion** — demo gallery, use case examples, interactive playground

---

## 🏗 Phase 3: Scale & Specialize (Later)

Focus: Production-ready document intelligence platform.

- **Authentication & multi-tenancy** — gate all endpoints including /queue/stats; add tenant model across upload, chat, and queue
- **Specialized pipelines** — legal, academic, or code document handling
- **Ecosystem growth** — community integrations, example applications
- **Frontend maturity** — full documentation site with live API explorer and community showcase gallery

---

## 📌 Notes

- Issue status (blocked, in progress, etc.) is visible when you click through to GitHub.
- This roadmap provides a quick overview; click any link for full issue details.
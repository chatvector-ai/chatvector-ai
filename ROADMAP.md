# ChatVector-AI Development Roadmap

This document outlines the current development focus and future direction of the ChatVector-AI project. It is intended for contributors to quickly understand priorities and pick up tasks.

---

## 🎮 Fun Beginner-Friendly Issues 

These issues are perfect for first-time contributors. They're well-scoped, have clear instructions, and let you add some personality to the project while exploring the codebase, project setup and collaborative GitHub PR process.

**Note:** No need to understand the codebase or RAG concepts to contribute here!

| Issue | What You'll Build | Impact | Skill Level |
|-------|-----------------|--------|-------------|
| [#87 Add GIF Preview for Demo or Contributing Video Links](https://github.com/chatvector-ai/chatvector-ai/issues/87) | Add small GIF previews inline with the Demo Video or Contributing Video badges in the README | Improve visual engagement and preview for contributors | Beginner |
| [#86 Add License Badge to Quick Links in README](https://github.com/chatvector-ai/chatvector-ai/issues/86) | Add a license badge to the Quick Links section of the README for better visibility | Make licensing clear to new users/contributors | Beginner |
| [#85 Add Python & FastAPI Version Badges to README](https://github.com/chatvector-ai/chatvector-ai/issues/85) | Display the Python and FastAPI versions as badges in the README | Improve transparency and ease onboarding | Beginner |
| [#83 Enhance Root Endpoint with Clickable Links to Docs and Status](https://github.com/chatvector-ai/chatvector-ai/issues/83) | Update the root ASCII page to include clickable links to documentation and status endpoints | Improve developer UX for testing the backend | Beginner |
| [#58 Add Setup Demo Video to Quick Links](https://github.com/chatvector-ai/chatvector-ai/issues/58) | Record a short setup demo and add it to the README | Be the face of the project and help future contributors get started | Beginner |
| [#24 Normalize PDF Text in Ingestion Pipeline](https://github.com/chatvector-ai/chatvector-ai/issues/24) | Clean up extracted PDF text (fix line breaks, normalize whitespace, handle special characters) | Improve downstream retrieval and RAG answer accuracy | Beginner |

**All beginner issues are tagged with** `good first issue` • `beginner-friendly` • `first-timers-only`

---

## 🚀 Phase 1: Stabilize & Optimize Core Engine (Current)

- **Focus:** Hardening the RAG backend for **reliability, observability, and performance**. 
- **Emphasis:** Advanced logging, ingestion pipeline robustness, asynchronous and batch processing foundations, chunking quality, and comprehensive error handling. 
- Completion of these tasks is critical before starting Phase 2.

---

### 🧱 Core Reliability & Architecture

| Issue | Description | Skill Level |
|-------|-------------|-------------|
| [#74 Refactor: Move Upload Pipeline Logic to Dedicated Service](https://github.com/chatvector-ai/chatvector-ai/issues/74) | Extract upload/ingestion logic into a dedicated service layer for improved maintainability and separation of concerns | Advanced |
| [#72 Update embedding service to use centralized retry utility](https://github.com/chatvector-ai/chatvector-ai/issues/72) | Refactor embedding calls to use a shared retry utility for consistency and resilience | Intermediate |
| [#45 Align Terminology: Use "Ingestion" Instead of "Upload"](https://github.com/chatvector-ai/chatvector-ai/issues/45) | Standardize terminology throughout the codebase and documentation | Beginner |
| [#79 Add real system metrics to /status endpoint](https://github.com/chatvector-ai/chatvector-ai/issues/79) | Replace mock data in `/status` endpoint with real system metrics (CPU, memory, disk, etc.) for immediate observability | Beginner/Intermediate |

---

### ⚡ Performance & Observability

| Issue | Description | Skill Level |
|-------|-------------|-------------|
| [#31 Async / Batch Retrieval for Chat Endpoint](https://github.com/chatvector-ai/chatvector-ai/issues/31) | Optimize chat responses by retrieving and processing context in parallel | Advanced |
| [#28 Implement Embedding Queue for Production Scaling](https://github.com/chatvector-ai/chatvector-ai/issues/28) | Build background queue system to handle embedding generation at scale without rate limits or timeouts | Advanced |
| [#22 Research Centralized Logging Integration](https://github.com/chatvector-ai/chatvector-ai/issues/22) | Investigate options for shipping logs to services like DataDog, Splunk, or ELK | Research |

---

### 🧠 RAG Enhancements (Answer Quality)

| Issue | Description | Skill Level |
|-------|-------------|-------------|
| [#23 Enhance Chunk Metadata Storage](https://github.com/chatvector-ai/chatvector-ai/issues/23) | Store additional metadata (page numbers, headings, timestamps) with each chunk | Beginner |
| [#25 Tune Chunk Size and Overlap](https://github.com/chatvector-ai/chatvector-ai/issues/25) | Experiment with different chunk sizes and overlaps to optimize retrieval quality | Beginner |
| [#26 Add Source Citation Support for LLM Answers](https://github.com/chatvector-ai/chatvector-ai/issues/26) | Make LLM responses include references to source documents and specific chunks | Beginner |

---

## 🎨 Frontend

The frontend is the face of ChatVector and demonstrates what's possible. It's designed to:
- **Showcase demos** of different RAG use cases
- **Provide a testing ground** for developers to experiment with the API
- **Inspire adoption** by showing real-world examples
- **Eventually host community contributions**

While the backend is the core engine, the frontend is the face of ChatVector — and we want it to be polished and intuitive.

| Issue | Description | Skill Level |
|-------|-------------|-------------|
| [#2 Create chat page layout](https://github.com/chatvector-ai/chatvector-ai/issues/2) | Build the basic UI structure for the chat interface (message bubbles, input field, send button) | Beginner |
| [#5 Add document upload to chat page](https://github.com/chatvector-ai/chatvector-ai/issues/5) | Integrate the upload component into the chat interface | Beginner |

---

## 🚧 Phase 2: Enhance Developer Experience (Next)

Focus: Make ChatVector-AI easier to adopt, extend, and integrate.

* Developer tools: Client SDKs, deployment improvements
* Advanced caching: Redis for embedding and response caching
* Extended RAG features: Advanced chunking, query transformations, prompt tuning
* **Frontend expansion:** Demo gallery, use case examples, interactive playground

---

## 🏗 Phase 3: Scale & Specialize (Later)

Focus: Production-ready document intelligence platform.

* Enterprise features: Authentication, multi-tenancy, monitoring
* Specialized pipelines: Legal, academic, or code documents
* Ecosystem growth: Community integrations, example applications
* **Frontend maturity:** Full documentation site with live API explorer and community showcase gallery

---

### 📌 Notes

* "Good First Issue" tags highlight tasks suitable for new contributors.
* **New contributors should start with the 🎮 Fun Beginner-Friendly Issues section!**
* Issue status (blocked, in progress, etc.) is visible when you click through to GitHub.
* This roadmap provides a quick overview; click any link for full issue details.
* #28 is critical for production scaling — ensures embedding generation doesn't become a bottleneck under load.
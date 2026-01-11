# ChatVector-AI Development Roadmap

This document outlines the current development focus and future direction of the ChatVector-AI project. It is intended for contributors to quickly understand priorities and pick up tasks.

---

## 🎯 Phase 1: Stabilize & Optimize Core Engine (Current)

- **Focus:** Hardening the RAG backend for **reliability, observability, and performance**. 
- **Emphasis:** Advanced logging, ingestion pipeline robustness, asynchronous and batch processing foundations, chunking quality, and comprehensive error handling. 
- Completion of these tasks is critical before starting Phase 2.

### 🔴 Critical / Blocking Issues

* [#44 Enhance `insert_chunk` with retry logic](https://github.com/chatvector-ai/chatvector-ai/issues/44) – blocks #43, #46
* [#27 Implement batch chunk insertions](https://github.com/chatvector-ai/chatvector-ai/issues/27) – blocks #28
* [#43 Validation & error handling in upload pipeline](https://github.com/chatvector-ai/chatvector-ai/issues/43) – blocks #46

### 🟡 Performance & Observability Enhancements

* [#20 Implement JSON logging format](https://github.com/chatvector-ai/chatvector-ai/issues/20) – Good First Issue
* [#21 Add request / correlation IDs](https://github.com/chatvector-ai/chatvector-ai/issues/21) – Good First Issue
* [#22 Research centralized logging integration](https://github.com/chatvector-ai/chatvector-ai/issues/22) – Research / Blocked
* [#31 Async / batch retrieval for chat endpoint](https://github.com/chatvector-ai/chatvector-ai/issues/31) – Advanced / Ready (design)
* [#28 Implement async embedding queue](https://github.com/chatvector-ai/chatvector-ai/issues/28) – Advanced / Blocked by #27

### 🟢 Ready for Development (Answer Quality / RAG Enhancements)

* [#23 Enhance chunk metadata storage](https://github.com/chatvector-ai/chatvector-ai/issues/23) – Good First Issue
* [#24 Normalize PDF text in ingestion pipeline](https://github.com/chatvector-ai/chatvector-ai/issues/24) – Good First Issue
* [#25 Tune chunk size & overlap](https://github.com/chatvector-ai/chatvector-ai/issues/25) – Good First Issue
* [#26 Add source citation support](https://github.com/chatvector-ai/chatvector-ai/issues/26) – Good First Issue

### 📝 Documentation & Polish

* [#45 Align terminology: “Ingestion” vs “Upload”](https://github.com/chatvector-ai/chatvector-ai/issues/45) – Good First Issue
* [#2 Frontend demo improvements](https://github.com/chatvector-ai/chatvector-ai/issues/2)
* [#4 Frontend demo improvements](https://github.com/chatvector-ai/chatvector-ai/issues/4)
* [#5 Frontend demo improvements](https://github.com/chatvector-ai/chatvector-ai/issues/5)

---

## 🔮 Phase 2: Enhance Developer Experience (Next)

Focus: Make ChatVector-AI easier to adopt, extend, and integrate.

* Developer tools: Client SDKs, deployment improvements (e.g., Docker)
* Advanced caching: Redis for embedding and response caching
* Extended RAG features: Advanced chunking, query transformations, prompt tuning

---

## 🚀 Phase 3: Scale & Specialize (Later)

Focus: Production-ready document intelligence platform.

* Enterprise features: Authentication, multi-tenancy, monitoring
* Specialized pipelines: Legal, academic, or code documents
* Ecosystem growth: Community integrations, example applications

---

### ✅ Notes

* Critical / Blocking issues must be resolved before Phase 2 features can progress.
* “Good First Issue” tags highlight tasks suitable for new contributors.
* This roadmap is intended to provide a quick overview; contributors can click the links to jump directly to the GitHub issues.

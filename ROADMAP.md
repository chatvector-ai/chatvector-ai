# ChatVectorAI Development Roadmap

This document outlines the current development focus and future direction of the ChatVectorAI project. It is intended for contributors to understand our priorities and where they can help.

## 🎯 Current Phase: Stabilize & Optimize the Core Engine *(Now)*
Our immediate focus is on hardening the foundational RAG backend for reliability, observability, and performance. **This work blocks all Phase 2 features.**

### 🔴 **Critical Path** (Blockers for Phase 2):
These issues must be resolved before we can move to Phase 2:

| Priority | Issue | Description | Blocks | Status |
|----------|-------|-------------|--------|--------|
| **🔴 Blocking** | #44 | Enhance `insert_chunk` with Retry Logic | #43, #46 | **Needs Owner** |
| **🔴 Blocking** | #27 | Implement Batch Chunk Insertions | #28 | **Needs Owner** |
| **🔴 Blocking** | #43 | Validation & Error Handling in Upload Pipeline | #46 | Blocked by #44 |

### 🟡 **High Priority** (Performance & Observability):
Important enhancements that can progress in parallel:

| Area | Issue | Description | Good For | Status |
|------|-------|-------------|----------|--------|
| **Observability** | #20 | Implement JSON Logging Format | Good First Issue | **Ready** |
| **Observability** | #21 | Add Request/Correlation IDs | Good First Issue | **Ready** |
| **Observability** | #22 | Research Centralized Logging | Research | Blocked |
| **Performance** | #31 | Async/Batch Retrieval | Advanced | **Ready (Design)** |
| **Performance** | #28 | Implement Async Embedding Queue | Advanced | Blocked by #27 |

### 🟢 **Ready for Development** (Answer Quality):
These improve the core RAG experience and are ready for contributors:

| Issue | Description | Skill Level | Impact |
|-------|-------------|-------------|--------|
| #23 | Enhance Chunk Metadata Storage | Good First Issue | High |
| #24 | Normalize PDF Text in Ingestion | Good First Issue | Medium |
| #25 | Tune Chunk Size and Overlap | Good First Issue | High |
| #26 | Add Source Citation Support | Good First Issue | High |

### 📝 **Documentation & Polish**:
| Issue | Description | Skill Level |
|-------|-------------|-------------|
| #45 | Align Terminology: "Ingestion" vs "Upload" | Good First Issue |
| #2, #4, #5 | Frontend Demo Improvements | Frontend |

## 🔮 Next Phase: Enhance the Developer Experience *(Next)*
Once the core is stable, we will focus on making ChatVectorAI easier to adopt and integrate.
- **Developer Tools:** Create client SDKs and improve deployment (e.g., Docker).
- **Advanced Caching:** Implement Redis for embedding and response caching.
- **Extended RAG Features:** Explore advanced chunking strategies, query transformations, and prompt tuning.

## 🚀 Future Vision: Scale & Specialize *(Later)*
Looking ahead, we aim to position ChatVectorAI as a versatile platform for production document intelligence.
- **Enterprise Features:** Authentication, multi-tenancy, advanced monitoring.
- **Specialized Pipelines:** Optimizations for specific document types (legal, academic, code).
- **Ecosystem Growth:** Foster a community of integrations and example applications.


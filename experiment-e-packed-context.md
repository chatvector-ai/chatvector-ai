# Experiment E: Packed-Context Observability

- **Phase 6 Handle:** `P6-W4-E`
- **Issue:** Closes #728
- **Category:** Wave 4 — Experiments and evaluation (Research / Decision Artifact)
- **Status:** Complete (Decision: **ADOPT OPTION 2**)

> **Notice:** This document is an experiment decision artifact. Per the pre-registered requirements of #728, this issue does not authorize a production behavior change. Implementation of the recommended contract requires a separate future issue.

---

## 1. Executive Summary

When ChatVector executes retrieval, `RetrievalResult` retains both `retrieved_chunks` (all candidate chunks selected and ranked up to `match_count`) and `packed_chunks` (the subset that fits within `MAX_CONTEXT_CHARS`). However, the public API contract surfaces `sources` derived from all retrieved chunks without indicating which chunks actually reached the generation context. If context length limits force chunks to be dropped, clients and debuggers cannot determine whether a chunk was seen by the LLM.

This experiment evaluated three options across 64 evaluation turns (31 Brinewick evaluation benchmark queries and 33 turns across 11 conversational scenarios) under varying `match_count` thresholds ($k \in \{5, 10, 20\}$) at both default (`32,000` chars) and constrained (`2,000` chars) context caps:
1. **Option 1 (Full Packed Chunk Text in Debug Payload):** Adds the full assembled packed context string to `retrieval_debug`.
2. **Option 2 (Flags on Existing Source Citations):** Adds `packed: bool` (and `drop_reason: "context_cap_exceeded"` when `packed=false`) directly to items in `sources[]`.
3. **Option 3 (Status Quo):** No additional payload.

### Decision
**ADOPT OPTION 2.** 
- Option 2 distinguishes **100%** of dropped chunks with zero ambiguity.
- Added payload size is **16 bytes/source** (median) and **56 bytes/source** (max when dropped), well below the pre-registered threshold of **100 bytes/source**.
- Option 1 is rejected because packed chunk text does **not** differ from stored chunk text (chunks are included whole), and Option 1's payload bloat reaches **10.2 KB at p95** ($k=20$), exceeding the 8 KB limit.
- Option 3 is rejected because drops can be readily forced under constrained budgets or multi-turn sessions, leaving debuggers blind to whether evidence reached generation.

---

## 2. Hypothesis & Problem Statement

### Hypothesis
`packed` and `dropped` flags on existing source entries answer "did the chunk reach the model" at negligible size, so full packed text in debug payloads is unnecessary.

### Audit Evidence & Context
1. **Product Reality (Confidence Matrix):** The audit confidence matrix highlighted an observability gap: *"What evidence reached generation?"* Currently, a source citation indicates retrieval rank and score, but not context inclusion.
2. **Realistic RAG:** In multi-turn chat sessions or when `max_context_chars` is restricted via presets or request overrides, later-ranked chunks are truncated by `backend/services/context_service.py:build_context_from_chunks`.
3. **Existing Internal State:** `RetrievalResult` in `backend/services/chat_service.py` already holds `retrieved_chunks` and `packed_chunks`. The data exists at runtime, but is omitted from the serialization boundary.

---

## 3. Options Evaluated

### Option 1: Full Packed Chunk Text in Debug Payload
- **Contract:** Adds `"packed_context": "<full formatted context string>"` to `retrieval_debug`.
- **Intended Value:** Gives exact prompt string passed to the LLM.
- **Drawbacks:** Substantial payload bloat (kilobytes per response), duplicates text already stored in documents/chunks, and transfers prompt boilerplate over the wire.

### Option 2: Lightweight Flags on Existing Source Entries
- **Contract:** Extends each object in `ChatResponse.sources` with:
  - `"packed": true` when the chunk was included in `packed_chunks`.
  - `"packed": false` and `"drop_reason": "context_cap_exceeded"` when dropped by `build_context_from_chunks`.
- **Intended Value:** Precise, per-citation observability into model visibility with near-zero wire overhead.

### Option 3: Status Quo (No Additional Payload)
- **Contract:** Maintain current schema where `sources` only reflects retrieved candidates and `retrieval_debug` omits packed chunk tracking.
- **Drawbacks:** Callers cannot verify if a cited chunk reached generation.

---

## 4. Methodology & Test Setup

- **Corpus:** Synthetic enterprise Brinewick Transit Cooperative corpus (31 documents, 42 chunks using `fixed`/1000/200).
- **Workload:**
  - 31 realistic-RAG queries from `backend/eval/brinewick/questions.json`.
  - 33 conversational scenario turns across 11 scenario scripts from `backend/eval/brinewick/scenarios/*.json`.
  - Total: **64 evaluated turns** per configuration.
- **Configurations Tested:**
  - Context caps: Default (`MAX_CONTEXT_CHARS=32000`) and Constrained (`max_chars=2000`) to force drops.
  - Candidate bounds: `match_count` $\in \{5, 10, 20\}$.
- **Metrics Collected:**
  - Added bytes per response (median, p95, max) for Option 1 and Option 2 relative to Option 3 baseline (measured using JSON UTF-8 serialization).
  - Added bytes per source citation for Option 2.
  - Number of cases where a retrieved chunk was not packed.
  - Drop distinction rate (whether Option 2 distinguishes all dropped chunks).
  - Text transformation check (whether packed text mutates chunk text).

---

## 5. Experimental Data & Size Tables

### Table 1: Default Context Cap (`MAX_CONTEXT_CHARS = 32,000`)

At the default 32,000 character limit, candidate chunks fit comfortably without drops across both corpora:

| `match_count` | Retr. Chunks | Packed Chunks | Dropped Chunks | Opt 1 Added (Med / p95 / Max) | Opt 2 Added (Med / p95 / Max) | Opt 2 Bytes / Source |
|---|---|---|---|---|---|---|
| **$k = 5$** | 320 | 320 | 0 | 2,331 B / 3,787 B / 4,256 B | 80 B / 80 B / 80 B | 16 B (med) / 16 B (max) |
| **$k = 10$** | 640 | 640 | 0 | 4,297 B / 5,753 B / 6,222 B | 160 B / 160 B / 160 B | 16 B (med) / 16 B (max) |
| **$k = 20$** | 1280 | 1280 | 0 | 9,045 B / **10,194 B** / 10,663 B | 320 B / 320 B / 320 B | 16 B (med) / 16 B (max) |

### Table 2: Constrained Context Cap (`max_chars = 2,000`)

Under a constrained budget (simulating long conversations or restrictive context configs), drops occur across all 64 runs:

| `match_count` | Retr. Chunks | Packed Chunks | Dropped Chunks | Runs w/ Drops | Opt 1 Added (Med / p95 / Max) | Opt 2 Added (Med / p95 / Max) | Opt 2 Bytes / Source |
|---|---|---|---|---|---|---|---|
| **$k = 5$** | 320 | 215 | 105 (32.8%) | 64 / 64 (100%) | 1,786 B / 1,955 B / 2,015 B | 120 B / 230 B / 280 B | 16 B (med) / 56 B (max) |
| **$k = 10$** | 640 | 215 | 425 (66.4%) | 64 / 64 (100%) | 1,786 B / 1,955 B / 2,015 B | 400 B / 510 B / 560 B | 56 B (med) / 56 B (max) |
| **$k = 20$** | 1280 | 215 | 1065 (83.2%) | 64 / 64 (100%) | 1,786 B / 1,955 B / 2,015 B | 960 B / 1,070 B / 1,120 B | 56 B (med) / 56 B (max) |

---

## 6. Verification Against Pre-Registered Adoption Criteria

| Pre-Registered Criterion | Required Outcome | Observed Result | Pass / Fail |
|---|---|---|---|
| **Option 3 Test** | Choose Option 3 if no retrieved-but-unpacked case occurs at default settings **and** no audit finding needed it. | Drops can be forced in 100% of constrained runs, and the Product Reality confidence matrix explicitly requires proof of what evidence reached generation. | **Rejected** |
| **Option 1 Text Difference Test** | Choose Option 1 only if packed text differs from stored chunk text in a way Option 2 cannot show (e.g. formatting or truncation). | `build_context_from_chunks` preserves chunks whole from start to finish without internal text modification or truncation (`text_differs = False`). | **Rejected** |
| **Option 1 Size Limit Test** | Option 1 p95 added size must remain below 8 KB. | At $k=20$, Option 1 p95 added size is **10,194 bytes (~10.2 KB)**, failing the 8 KB cap. | **Rejected** |
| **Option 2 Diagnostic Power** | Option 2 must distinguish every single retrieved-but-unpacked case. | Option 2 distinguishes **100%** of dropped chunks across all 64 runs and all $k$ values (`distinguishes_all = True`). | **Passed** |
| **Option 2 Size Limit Test** | Option 2 added size must be at most **100 bytes per source**. | Option 2 added bytes per source is **16 bytes** (packed) and **56 bytes** (dropped), well below the 100-byte cap. | **Passed** |

---

## 7. Architectural Recommendation & Contract Specification

### Adoption Decision
**Adopt Option 2.**

### Proposed Production Contract (For Future Implementation Issue)
When implementing in a future issue:

1. **`ChatSourceResponse` (`backend/routes/chat.py`):**
   ```python
   class ChatSourceResponse(BaseModel):
       file_name: Optional[str] = None
       page_number: Optional[int] = None
       page_end: Optional[int] = None
       chunk_index: Optional[int] = None
       score: Optional[float] = None
       # Proposed Additive Fields:
       packed: bool = Field(
           default=True,
           description="True if this chunk was assembled into the LLM context; False if dropped."
       )
       drop_reason: Optional[Literal["context_cap_exceeded"]] = Field(
           default=None,
           description="Reason why the chunk was excluded from the generation context."
       )
   ```

2. **`_build_sources` Mapping (`backend/services/chat_service.py`):**
   Pass `packed_chunks` to `_build_sources(retrieved_chunks, packed_chunks)`.
   ```python
   packed_ids = {c.id for c in packed_chunks}
   for chunk in retrieved_chunks:
       is_packed = chunk.id in packed_ids
       source = {
           ...,
           "packed": is_packed,
       }
       if not is_packed:
           source["drop_reason"] = "context_cap_exceeded"
   ```

3. **Client Non-Breaking Guarantee:**
   Because `packed` and `drop_reason` are purely additive fields on existing citation objects, existing Python and TypeScript SDKs and frontend consumers will parse responses without breaking.

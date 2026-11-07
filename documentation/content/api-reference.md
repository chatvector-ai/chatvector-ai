# API Reference

The reference below is generated from the FastAPI OpenAPI schema exported from `backend/main.py` at documentation build time.

!!! note "Production environments"
    Live Swagger UI (`/docs`), ReDoc (`/redoc`), and `/openapi.json` are **disabled** when `APP_ENV=production`. Use this static reference or export the schema from a non-production environment.

## Authentication

| Environment | Auth behavior |
|-------------|---------------|
| `APP_ENV=development` or `test` | Auth bypass — no API key required |
| `APP_ENV=production` | Bearer token required on protected routes |

Protected routes expect:

```http
Authorization: Bearer cv_live_<prefix>.<secret>
```

Create keys with `python -m backend.cli create-tenant-key`. See [Getting Started](getting-started.md#generate-an-api-key).

## Major routes

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/upload` | Upload a document for background ingestion |
| `GET` | `/documents` | List tenant document summaries |
| `GET` | `/documents/{document_id}/status` | Poll ingestion status |
| `GET` | `/documents/{document_id}/status/stream` | SSE ingestion progress |
| `DELETE` | `/documents/{document_id}` | Delete a document |
| `POST` | `/chat` | RAG chat (non-streaming) |
| `POST` | `/chat/stream` | RAG chat (SSE streaming) |
| `POST` | `/chat/batch` | Batch compare or synthesize |
| `POST` | `/sessions` | Create a chat session |
| `GET` | `/sessions` | List sessions |
| `GET` | `/sessions/{session_id}` | Get session metadata |
| `GET` | `/sessions/{session_id}/history` | Session message history |
| `DELETE` | `/sessions/{session_id}` | Delete a session |
| `POST` | `/feedback` | Submit structured retrieval or answer feedback |
| `GET` | `/feedback` | List feedback for the authenticated tenant |
| `GET` | `/status` | Service health and configuration summary |
| `GET` | `/queue/stats` | Ingestion queue statistics |

## Idempotency keys

`POST /upload` and `POST /sessions` accept an optional request header:

```http
Idempotency-Key: <client-chosen string, max 255 characters>
```

When the header is **omitted**, the request runs normally and is not replayed.

When the header is **present**, the server stores the response in Redis keyed by `(tenant_id, route, idempotency_key)` for `IDEMPOTENCY_TTL_SECONDS` (default 86400):

| Route | Request fingerprint (must match for replay) |
|-------|---------------------------------------------|
| `POST /upload` | SHA-256 of file bytes, normalized filename, `Content-Type` when sent, `replace_document_id` when present, and canonical JSON of `metadata` (key order does not matter; omitting metadata is distinct from `{}`) |
| `POST /sessions` | Optional JSON `session_id` field (tenant is scoped by auth) |

Semantics:

- Same key and same fingerprint while a stored response exists → replay the stored HTTP status and body (including the same `document_id` or `session_id`).
- Same key and different fingerprint → `409` with `code: idempotency_key_mismatch`.
- Concurrent in-flight requests with the same key and fingerprint → the second waits for the first to finish (up to `IDEMPOTENCY_WAIT_TIMEOUT_SECONDS`, default 30s), then replays; only one document or session is created.
- After TTL expiry the key may be reused; a retry with a reused key is a new operation.
- Transient results are not stored: HTTP 429, HTTP 503 (including `queue_full`), and in-flight 409 codes `replacement_in_progress`, `document_processing`, and `idempotency_in_progress` release the key so a later retry can succeed. Deterministic 422 responses and fingerprint mismatches stay replayable.

SDKs expose optional `idempotency_key` / `idempotencyKey` on upload and session create. The SDK does **not** automatically retry mutating POST requests.

## Document metadata

`POST /upload` accepts an optional multipart form field `metadata`: a JSON object of flat key/value pairs, for example `{"department": "legal", "year": 2026, "final": true}`. Values must be strings, numbers, or booleans. Nested objects, arrays, `null` values, non-object JSON (including a top-level array), and invalid JSON are rejected with `422`. Omitting `metadata` stores `{}`.

`GET /documents` and `GET /documents/{document_id}/status` return the stored object as `metadata`. Size is bounded by `DOCUMENT_METADATA_MAX_KEYS` (default 20) and `DOCUMENT_METADATA_MAX_BYTES` (default 4096). Retrieval can be narrowed by metadata with `metadata_filter` (see [Retrieval overrides](#retrieval-overrides)).

## Replacing a document

`POST /upload` accepts an optional multipart form field `replace_document_id` (a UUID). Instead of creating a new document, the upload re-ingests the file into that existing document, which keeps its `document_id`. Chat sessions bound to the document keep working after the swap. Omitting the field creates a new `document_id` as before.

Replacement is staged:

- While the new file is being processed, the document stays `completed` and its **prior content remains retrievable**. `GET /documents/{document_id}/status`, the status stream, and `GET /documents` report `status_detail: "replacement_in_progress"` (the upload response includes it too). Retrieval and chat never see a mix of old and new chunks from the cutover itself.
- On success the old chunks are swapped for the new ones in one transaction. `file_name` and `metadata` are updated to the new upload's values, and `status_detail` is cleared. Clients should wait for `status_detail` to clear, not for `status == "completed"`, which is already true.
- On failure the prior content is left untouched, `status` is not changed to `failed`, and the document reports `status_detail: "replacement_failed"` with an `error` object. A later replacement can be attempted.

Eligible documents are tenant-owned documents in `completed` or `failed` state with no replacement already running.

| Status | `code` | Meaning |
|--------|--------|---------|
| `404` | `document_not_found` | No such document for this tenant |
| `409` | `replacement_in_progress` | A replacement is already running for this document |
| `409` | `document_processing` | The document is still in its initial ingestion |
| `422` | `invalid_replace_document_id` | `replace_document_id` is not a valid UUID |

`DELETE /documents/{document_id}` returns `409` with `document_replacing` while a replacement is running.

Not included: version history, `document_key` upsert, bulk replace, and content-hash dedup. Hybrid retrieval issues two statements per request, so a single request that straddles the exact commit instant of a cutover could in principle mix old and new chunks. Each statement and the cutover itself are atomic.

Existing databases need migration `backend/db/init/014_document_replacement.sql` (adds `documents.status_detail`) applied with `psql -f`.

## Retrieval overrides

`POST /chat`, `POST /chat/stream`, and `POST /chat/batch` accept optional retrieval overrides. Set them as top-level fields or inside a `retrieval` object. For each field, an explicit top-level value wins over the nested `retrieval` object, which wins over a named preset, which wins over the process environment. Omitting retrieval config keeps the process defaults (vector retrieval, hybrid and reranking off, rewrite/expand/step-back off).

| Field | Meaning |
|-------|---------|
| `match_count` | Chunks to retrieve. May stay top-level; it merges into the effective config. |
| `scope` | `session` or `tenant`. Same merge rule as `match_count`. |
| `hybrid_enabled` | Override `HYBRID_RETRIEVAL_ENABLED` for this request. |
| `reranking_enabled` | Override `ENABLE_RERANKING` for this request. |
| `reranker_provider` | Override `RERANKER_PROVIDER` when reranking runs. Accepts `similarity` (in-process) or `cohere` (hosted; needs `COHERE_API_KEY` on the server). A hosted provider failure falls back to retrieval order. |
| `query_transformation_enabled` | Explicitly enable or disable query transformation. |
| `query_transformation_strategy` | `rewrite`, `expand`, `stepback`, or `none`. |
| `skip_history_transform` | When `false` on a compare-style batch item, session history is passed into query transformation. |
| `metadata_filter` | Narrow which in-scope documents participate in retrieval by their stored document metadata. See below. |

A strategy other than `none` enables transformation for that request even when `QUERY_TRANSFORMATION_ENABLED=false`. `query_transformation_enabled=false` disables it even if a strategy is set. `query_transformation_enabled=true` with strategy `none` does not run rewrite, expand, or step-back. Those strategies are never turned on by omission alone.

### Metadata filter

`metadata_filter` is an object whose keys are document metadata field names. Values are strings, numbers, or booleans, matching what `POST /upload` stores. Comparison is same-type, and strings are case-sensitive.

- Exact match: `{ "department": "legal" }`. The document must have the key and an equal value.
- Scalar in-list: `{ "department": { "in": ["legal", "hr"] } }`. The document value must equal one listed value. The list must be non-empty.
- Multiple keys are ANDed.

Nested objects, arrays as operands, `null`, an empty object, unknown operators, and any other shape are rejected with `422`. The filter is bounded by `DOCUMENT_METADATA_MAX_KEYS` and `DOCUMENT_METADATA_MAX_BYTES`. Array metadata such as tags is not supported in v1.

The filter applies at document level, after the session or tenant scope is resolved and always within the authenticated tenant. It cannot widen tenant or document scope. `doc_id` stays required on `POST /chat` and `POST /chat/stream`. The anchor document must itself match the filter. Otherwise chat, stream, and batch return `anchor_document_excluded_by_filter` (an `error` event on the stream). Omitting `metadata_filter` leaves retrieval unchanged.

### Named presets

`retrieval.preset` names a config object loaded at process startup from `RETRIEVAL_PRESETS_PATH` and/or `RETRIEVAL_PRESETS`. A preset is an alias for the same retrieval fields as a request override, including query-transformation settings. Precedence is explicit request field, then the nested `retrieval` object, then the preset, then the process environment. There is no database or admin UI for presets.

Unknown preset names return 400 `preset_not_found` on `/chat`, `/chat/stream`, and `/chat/batch` before a stream starts. Invalid preset values fail at startup. An invalid `RERANKER_PROVIDER` environment name also fails at startup; a live Cohere call that times out or errors still falls back to pre-rerank order.

## Ingestion status

`GET /documents/{id}/status` and the status SSE stream report pipeline state. Typical values include `uploaded`, `queued`, `extracting`, `chunking`, `embedding`, `storing`, `retrying`, `completed`, and `failed`. `retrying` is not terminal: status clients should keep reading, and `ingestion.failed` is not sent, until retries are exhausted or the error is not retryable. Terminal success sends `ingestion.completed` only when webhooks are enabled. Both payloads include `file_name` from the document row when it is set. During a replacement that name stays the previous file until cutover, then becomes the new file's name.

The optional `job` object can include `attempt`, timestamps, and `failure_class` on a terminal failure. A missing durable artifact is a terminal failure with a `job_payload_missing` classification.

## Retrieval debug

Set `debug_retrieval` to `true` as a query parameter or request field. The response adds `retrieval_debug`. It is diagnostic. Useful fields include `effective_config` (resolved value and source `request`, `preset`, or `env`), the effective retrieval query, history-considered / skip reason, `history_resolution_latency_ms` when a resolution call ran, retrieval and rerank timings, component scores, and `reranker.fallback_reason` when a hosted reranker fell back. Stream `complete.latency_ms` is generation time only. `request_latency_ms` includes history resolution and retrieval.

## Evaluation

`python -m backend.cli eval` scores retrieval with recall@k, MRR, and nDCG against a JSON fixture. It calls the same retrieval path as chat and does not generate answers. The embedding cache is bypassed unless `--allow-cache` is set. See [DEVELOPMENT.md](https://github.com/chatvector-ai/chatvector-ai/blob/main/DEVELOPMENT.md) under "Retrieval evaluation".

## Experimental GraphRAG

`ENABLE_GRAPH_RETRIEVAL` defaults to false. With the flag off, retrieval does not load graph code or extra dependencies. With the flag on, expanded neighbors are limited to the request's already authorized document ids. This is not the default retrieval architecture. See the RFC in `backend/rfcs/graph-retrieval.md`.

## Retrieval feedback

`POST /feedback` records thumbs-up (`rating: 1`) or thumbs-down (`rating: -1`) signals tied to a session. Authentication is required; anonymous feedback is not supported. Stored feedback does not change ranking or prompts. `POST` and `GET` are rate-limited with `RATE_LIMIT_FEEDBACK` (default `60/minute`).

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | `answer`, `citation`, or `retrieval` |
| `rating` | yes | `-1` or `1` |
| `session_id` | yes | Session the feedback applies to (must belong to the authenticated tenant) |
| `comment` | no | Optional free-text note (max 4096 characters) |
| `message_id` | linkage | UUID of a chat message from `GET /sessions/{session_id}/history` |
| `document_id` | linkage | UUID of a tenant-owned document |
| `chunk_index` | no | Chunk index when citing a specific retrieved chunk |

**Linkage matrix (v1)**

| `type` | Required linkage |
|--------|------------------|
| `answer` | `message_id` must reference a message in `session_id` for this tenant |
| `citation` | `message_id` **or** (`document_id` with optional `chunk_index`) |
| `retrieval` | Same as `citation` |

When both `message_id` and `document_id` are sent, both are validated. Cross-tenant `message_id` or `document_id` values return `404` without revealing whether another tenant owns that id. Invalid combinations (for example `answer` without `message_id`, or `citation` without either message or document linkage) return `422`.

`document_id` and `session_id` are not foreign keys. Feedback rows are kept, with those ids, when the source document or session is deleted. `message_id` is set to null if that message is deleted.

`GET /feedback` supports optional query filters: `session_id`, `created_after`, `created_before` (ISO-8601 datetimes), and `limit` (default 50, max 200). Results are tenant-scoped.

Existing databases need migration `backend/db/init/017_retrieval_feedback.sql` applied with `psql -f`.

## History overrides

The same three endpoints accept an optional `history` object. It does not enable rewrite, expand, or step-back. Omitting it keeps the process defaults.

| Field | Meaning |
|-------|---------|
| `retrieval_history_window` | Recent messages used to decide and run standalone resolution. Integer 0–100. Default `QUERY_TRANSFORMATION_HISTORY_WINDOW` (6). Honored up to the system cap of 100; values above 100 are rejected. |
| `generation_history_window` | Recent messages injected into the answer context. Integer 0–100. Default `GENERATION_HISTORY_WINDOW` (10). Honored up to the system cap of 100; values above 100 are rejected. |
| `history_aware_retrieval` | When `true`, run the need-resolution gate. When explicitly `false`, never resolve history for that request. Default `HISTORY_AWARE_RETRIEVAL_DEFAULT` (true). |
| `max_generation_history_chars` | Optional cap on generation-history characters, applied before `MAX_CONTEXT_CHARS` drops chunks. |

An extra resolution LLM call happens only when `history_aware_retrieval` is effectively true, the retrieval window is non-empty, transform history is not skipped, and the gate decides the question depends on prior turns. The gate skips the call when the window is empty, the question is already a full standalone query (no unresolved pronouns, demonstratives such as "that clause" / "this section", or elliptical follow-ups such as "what about …" or "and the …"), or an explicit topic-switch cue is present without those references. Cues include "new topic", "switching topics", "change of subject", "different question", "unrelated question", "forget the previous", "ignore the previous", and "starting over". Ambiguous questions, including a topic cue that still contains a pronoun, still resolve.

`HISTORY_AWARE_RETRIEVAL_DEFAULT=false` with the field omitted turns the gate off: resolution runs only when `QUERY_TRANSFORMATION_ENABLED=true`, and then for every non-empty window. A failed resolution call falls back to the original question and does not fail the chat.

Compare-style batch items (one `doc_id`) still skip generation history and turn persistence. They also skip transform history unless `skip_history_transform` is explicitly false. A normal multi-document batch item with a session uses the history settings above.

### Effective retrieval query

After history resolution and transformation, one primary retrieval query is the first string in the final query list.

- Vector search embeds that primary query. `expand` and `stepback` still embed each query in the list and merge candidates.
- Hybrid keyword / full-text search uses the primary query, not the raw user question, when transformation or history resolution changed the text.
- Hybrid fusion uses this request's `hybrid_enabled` value.
- Reranking scores candidates against the primary query.
- With `debug_retrieval=true`, `retrieval_debug.reranker` reports `provider`, `model`, `latency_ms`, `candidates_sent`, and `fallback_reason` when reranking ran.

`RETRIEVAL_MAX_CONCURRENCY`, embedding model selection, provider API keys, and queue settings stay process-level. `MAX_CONTEXT_CHARS` is not request-configurable; debug and eval snapshots still record the resolved process value.

There is no public HTTP retrieval endpoint. Chat still generates the answer. Eval and other internal callers use `retrieve_for_documents`.

## Interactive schema

<swagger-ui src="assets/openapi.json"/>

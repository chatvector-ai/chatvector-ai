# ChatVector Python SDK

Lightweight official Python client for the ChatVector API.

The SDK wraps the core document-ingestion and chat endpoints behind a clean synchronous interface, returns typed dataclass models, and maps API and transport failures to a small custom exception hierarchy.

## Requirements

- Python 3.10+
- `httpx` is the only runtime dependency

## Installation

From the repository root:

```bash
pip install ./sdk/python
```

For local development:

```bash
pip install -e ./sdk/python
```

## Development / Running Tests

```bash
pip install -e ".[dev]"
pytest sdk/python/tests/
```

## Quickstart

```python
from chatvector import ChatVectorClient

with ChatVectorClient(base_url="http://localhost:8000") as client:
    upload = client.upload_document("handbook.pdf")
    ready = client.wait_for_ready(upload.document_id, timeout=90, interval=3)
    answer = client.chat(
        question="What are the onboarding steps?",
        doc_id=ready.document_id,
        match_count=3,
    )

print(upload.document_id, ready.status)
print(answer.answer)
for source in answer.sources:
    print(source.file_name, source.page_number, source.chunk_index)
```

For ingestion progress over SSE instead of polling, see [Document Status Streaming](#document-status-streaming).

## Async Client

Use ``AsyncChatVectorClient`` in FastAPI and other async Python apps without
blocking the event loop:

```python
import asyncio

from chatvector import AsyncChatVectorClient

async def main() -> None:
    async with AsyncChatVectorClient(base_url="http://localhost:8000") as client:
        upload = await client.upload_document("handbook.pdf")
        ready = await client.wait_for_ready(upload.document_id, timeout=90, interval=3)
        answer = await client.chat(
            question="What are the onboarding steps?",
            doc_id=ready.document_id,
            match_count=3,
        )
        print(answer.answer)

asyncio.run(main())
```

Streaming chat works the same way with ``async for``:

```python
async for event in client.stream_chat("Summarize this", "doc-1"):
    if event.type == "token":
        print(event.content, end="")
```

The async client mirrors the sync surface for upload, status, ``wait_for_ready``,
chat, batch chat, sessions, and streaming chat. Document status SSE streaming
(``iter_document_status``) is supported on the async client as well.

## Authentication

ChatVector backends running with `APP_ENV=production` require an API key on every
request.  Pass the key to the client constructor; the SDK sends
`Authorization: Bearer <key>` on all requests automatically:

```python
from chatvector import ChatVectorClient

client = ChatVectorClient(
    base_url="https://api.chatvector.example",
    api_key="cv_live_yourprefixhere.yoursecrethere",
)
```

Generate a key with the backend CLI (run once per environment):

```bash
python -m backend.cli create-tenant-key --tenant "My Org" --tenant-id my-org
```

The raw key is printed **once** and is never stored.  Record it immediately.

In **development mode** (`APP_ENV=development`) the backend bypasses authentication
so the `api_key` parameter can be omitted locally:

```python
client = ChatVectorClient(base_url="http://localhost:8000")
```

## Sessions and Retrieval Scope

Create and manage chat sessions without raw HTTP calls. Documents are associated
with a session automatically when you chat with both a `doc_id` and `session_id`.

```python
from chatvector import ChatVectorClient

with ChatVectorClient(base_url="http://localhost:8000", api_key="cv_live_...") as client:
    session = client.create_session()

    response = client.chat(
        question="Summarize this document",
        doc_id="doc-1",
        session_id=session.id,
    )

    response = client.chat(
        question="What do we know across all documents?",
        doc_id="doc-1",
        session_id=session.id,
        scope="tenant",
    )

    sessions = client.list_sessions()
    client.delete_session(session.id)
```

If `session_id` is omitted, the backend preserves its automatic session-creation
behavior. Retrieval scope defaults to `"session"`; use `"tenant"` to search across
all documents for the authenticated tenant.

## Retrieval and history configuration

Pass optional ``RetrievalConfig`` and ``HistoryConfig`` objects on ``chat()``,
``stream_chat()``, and ``batch_chat()``. They serialize to nested ``retrieval`` and
``history`` JSON objects using the same snake_case keys as the backend API. Unset
fields are omitted (not sent as JSON ``null``).

```python
from chatvector import ChatVectorClient, HistoryConfig, RetrievalConfig

with ChatVectorClient(base_url="http://localhost:8000") as client:
    retrieval = RetrievalConfig(
        match_count=8,
        hybrid_enabled=True,
        query_transformation_strategy="expand",
    )
    history = HistoryConfig(retrieval_history_window=4, history_aware_retrieval=False)

    answer = client.chat(
        "Summarize recent context",
        "doc-1",
        retrieval=retrieval,
        history=history,
    )
```

| Python field | JSON key |
| --- | --- |
| ``match_count`` | ``match_count`` |
| ``scope`` | ``scope`` |
| ``hybrid_enabled`` | ``hybrid_enabled`` |
| ``reranking_enabled`` | ``reranking_enabled`` |
| ``reranker_provider`` | ``reranker_provider`` |
| ``query_transformation_enabled`` | ``query_transformation_enabled`` |
| ``query_transformation_strategy`` | ``query_transformation_strategy`` |
| ``skip_history_transform`` | ``skip_history_transform`` |
| ``metadata_filter`` | ``metadata_filter`` |
| ``preset`` | ``preset`` |
| ``retrieval_history_window`` | ``retrieval_history_window`` |
| ``generation_history_window`` | ``generation_history_window`` |
| ``history_aware_retrieval`` | ``history_aware_retrieval`` |
| ``max_generation_history_chars`` | ``max_generation_history_chars`` |

The SDK rejects ``match_count`` outside 1–20 before sending a request. Other
validation remains on the backend (422 responses surface through existing SDK errors).

``metadata_filter`` is sent as the backend filter object and is omitted when unset.
The client does not evaluate filters locally. ``upload_document(..., metadata=...)``
sends that object as the multipart JSON ``metadata`` field. ``post_feedback`` and
``list_feedback`` call ``/feedback``; stored feedback does not change retrieval.

## Streaming Chat

Stream token-by-token answers over Server-Sent Events without manually parsing SSE.

```python
from chatvector import ChatVectorClient

with ChatVectorClient(base_url="http://localhost:8000", api_key="cv_live_...") as client:
    for event in client.stream_chat(
        question="Summarize this document",
        doc_id="doc-1",
        session_id="sess-1",
        scope="session",
        timeout=60,
    ):
        if event.type == "token":
            print(event.content, end="")
        elif event.type == "complete":
            print(event.sources)
            print(event.session_id, event.model, event.latency_ms)
```

The SDK yields typed `token` and `complete` events. Backend `error` events are
converted into structured SDK exceptions. Legacy `[DONE]` completion markers are
ignored for backward compatibility.

Each `sources[]` item may include `score` and `score_type` (`vector`,
`hybrid_rrf`, or `reranked`) plus component scores (`vector_score`,
`full_text_score`, `rrf_score`, `reranker_score`, and `rerank_order`) when the
backend sends them. Scores are only comparable within the same
`score_type`; see `DEVELOPMENT.md` for semantics.

Non-streaming `chat()` responses include `latency_ms` and `model` on the
`ChatResponse` dataclass (same fields as the `complete` event in streaming).

## Document Status Streaming

Subscribe to ingestion progress over SSE instead of polling `wait_for_ready()`.

```python
from chatvector import ChatVectorClient

with ChatVectorClient(base_url="http://localhost:8000", api_key="cv_live_...") as client:
    upload = client.upload_document("handbook.pdf")

    for status in client.iter_document_status(upload.document_id, timeout=120):
        print(status.status, status.chunks, status.queue_position)
        if status.status in {"completed", "failed"}:
            break
```

Each event is a typed `DocumentStatus` snapshot. Backend `error` events are
converted into structured SDK exceptions. Stop iterating early to cancel the
stream; the SDK closes the underlying HTTP response automatically.
``AsyncChatVectorClient.iter_document_status`` yields the same snapshots with
``async for``.

## Replacing a Document

Pass `replace_document_id` to re-ingest a completed or failed document in
place. The document keeps its ID, its prior content stays retrievable until the
new content is ready, and bound sessions keep working.

```python
upload = client.upload_document("handbook-v2.pdf", replace_document_id=document_id)
print(upload.status, upload.status_detail)  # completed replacement_in_progress

client.wait_for_ready(document_id)  # waits for the swap; raises if the replacement failed
```

During a replacement `status` stays `completed` and `status_detail` is
`replacement_in_progress` (or `replacement_failed` afterwards), so check
`status_detail` rather than `status` when watching progress. A replacement that
is already running returns a `409` `ChatVectorAPIError`.

## Bulk document upload

Upload many files client-side with bounded concurrency (default 5). Each file
uses the existing ``POST /upload`` / ``POST /ingest`` flow; there is no server
batch endpoint in v1.

```python
from chatvector import ChatVectorClient

with ChatVectorClient(base_url="http://localhost:8000", api_key="cv_live_...") as client:
    summary = client.upload_many(
        ["a.pdf", "b.pdf", "c.pdf"],
        concurrency=3,
        on_progress=lambda result, agg: print(result.file_path, result.success, agg.success_count),
    )
    print(summary.success_count, summary.failure_count)

    folder_summary = client.upload_directory("./docs", pattern="*.pdf")
```

Failures are recorded per file; remaining uploads continue unless ``fail_fast=True``.
Optional ``retry_on_rate_limit=True`` enables bounded sleeps on HTTP 429 only when
you opt in (mutating uploads are not retried by default).

The default server upload rate limit is typically **20 uploads per hour** per
tenant. Large batches should expect **HTTP 429** (and occasional **503**
``queue_full`` when the processing queue is saturated) rather than uninterrupted
success.

## Batch Chat

Run multiple queries in one request. Each query can target a different document.

```python
from chatvector import ChatVectorClient, BatchChatQuery

with ChatVectorClient(base_url="http://localhost:8000", api_key="cv_live_...") as client:
    result = client.batch_chat(
        queries=[
            BatchChatQuery(question="Key risks?", doc_ids=["doc-1"]),
            BatchChatQuery(question="Revenue drivers?", doc_ids=["doc-2"]),
        ],
        session_id="sess-1",
        scope="session",
    )

    for item in result.results:
        print(item.question, item.answer, item.latency_ms)
```

## Error Handling

HTTP failures and transport errors raise typed exceptions:

- `ChatVectorAuthError` for `401` and `403`
- `ChatVectorRateLimitError` for `429`
- `ChatVectorTimeoutError` for `408`, `504`, and timeout/connection failures
- `ChatVectorAPIError` for other API or transport failures

Non-streaming `chat()` and `batch_chat()` return typed responses where HTTP 200 does not imply success — callers must check `response.status == "ok"` before using `answer`. Soft failures (such as provider errors or filter exclusions) return `status: "error"` and a structured `error` dict rather than raising exceptions. Streaming chat (`stream_chat()`) delivers errors via an `error` event and raises `ChatVectorAPIError`.

Example:

```python
from chatvector import ChatVectorAPIError, ChatVectorClient

try:
    with ChatVectorClient("http://localhost:8000") as client:
        response = client.chat("Summarize the document", "doc-123")
        if response.status == "ok":
            print(response.answer)
        else:
            print(f"Chat error: {response.error}")
except ChatVectorAPIError as exc:
    print(exc)
```

## Retry behavior

By default, eligible `GET` and `HEAD` requests are retried at most twice (three
total attempts) for connection/timeouts and HTTP 408, 429, 502, 503, or 504.
Backoff uses bounded exponential full jitter (cap 8s) and honors numeric
`Retry-After` headers as a sleep floor.

Mutating requests are never automatically replayed. This includes document
uploads, chat, streaming chat, batch chat, session creation, and session
deletion. Document upload and session creation accept an ``Idempotency-Key``;
pass ``idempotency_key`` on those methods when a retry must replay the same
result instead of creating a duplicate.

See [DEVELOPMENT.md — Retry behavior](../../DEVELOPMENT.md#retry-behavior) for
the full cross-surface contract shared with the backend and TypeScript SDK.

## Examples

See the runnable scripts in [examples](./examples):

- `upload_wait_chat.py`
- `check_status.py`
- `batch_chat.py`
- `session_chat.py`
- `stream_chat.py`

Server-side FastAPI proxy (upload → wait → session → chat):

- [examples/fastapi-proxy](./examples/fastapi-proxy/README.md)

## API Notes

The backend currently exposes document upload at `/upload`. The SDK targets `/ingest` as the forward-facing contract and transparently falls back to `/upload` for compatibility with the current repository backend.

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
`hybrid_rrf`, or `reranked`). Scores are only comparable within the same
`score_type`; see `DEVELOPMENT.md` for semantics.

Non-streaming `chat()` responses include `latency_ms` and `model` on the
`ChatResponse` dataclass (same fields as the `complete` event in streaming).

## Batch Chat

Run multiple queries in one request. Each query can target a different document.

```python
from chatvector import ChatVectorClient, BatchChatQuery

with ChatVectorClient(base_url="http://localhost:8000", api_key="cv_live_...") as client:
    result = client.batch_chat(
        queries=[
            BatchChatQuery(question="Key risks?", doc_id="doc-1"),
            BatchChatQuery(question="Revenue drivers?", doc_id="doc-2"),
        ],
        session_id="sess-1",
        scope="session",
    )

    for item in result.results:
        print(item.question, item.answer, item.latency_ms)
```

## Error Handling

All SDK methods raise typed exceptions:

- `ChatVectorAuthError` for `401` and `403`
- `ChatVectorRateLimitError` for `429`
- `ChatVectorTimeoutError` for `408`, `504`, and timeout/connection failures
- `ChatVectorAPIError` for other API or transport failures

Example:

```python
from chatvector import ChatVectorAPIError, ChatVectorClient

try:
    with ChatVectorClient("http://localhost:8000") as client:
        response = client.chat("Summarize the document", "doc-123")
except ChatVectorAPIError as exc:
    print(exc)
```

## Examples

See the runnable scripts in [examples](./examples):

- `upload_wait_chat.py`
- `check_status.py`
- `batch_chat.py`
- `session_chat.py`
- `stream_chat.py`

## API Notes

The backend currently exposes document upload at `/upload`. The SDK targets `/ingest` as the forward-facing contract and transparently falls back to `/upload` for compatibility with the current repository backend.

## Current Gaps

- **No async client** — synchronous `httpx` only
- **No ingestion SSE client** — use `wait_for_ready()` polling or call `/documents/{id}/status/stream` directly
- **No per-component retrieval scores** — citations expose collapsed `score` + `score_type` only

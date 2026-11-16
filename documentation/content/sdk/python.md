# Python SDK

The official Python client wraps document upload (including metadata, replacement, and bulk upload), ingestion status and SSE, chat, streaming, batch, sessions, retrieval and history config, metadata filters, feedback, and optional idempotency keys. Mutating POSTs are not retried automatically.

Full API details live in the repository: [`sdk/python/README.md`](https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/README.md).

## Installation

From the repository root:

```bash
pip install ./sdk/python
```

For development:

```bash
pip install -e ./sdk/python
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
    if answer.status == "ok":
        print(answer.answer)
```

## Async client

Use `AsyncChatVectorClient` in FastAPI and other async apps:

```python
from chatvector import AsyncChatVectorClient

async with AsyncChatVectorClient(base_url="http://localhost:8000") as client:
    upload = await client.upload_document("handbook.pdf")
    ready = await client.wait_for_ready(upload.document_id)
    answer = await client.chat(question="Summarize this.", doc_id=ready.document_id)
```

## Authentication

Production backends require an API key:

```python
ChatVectorClient(
    base_url="https://api.example.com",
    api_key="cv_live_yourprefix.yoursecret",
)
```

Local development with `APP_ENV=development` or `test` can omit `api_key`.

## Examples

Runnable scripts in the repository:

- [`sdk/python/examples/upload_wait_chat.py`](https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/examples/upload_wait_chat.py)
- [`sdk/python/examples/session_chat.py`](https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/examples/session_chat.py)
- [`sdk/python/examples/stream_chat.py`](https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/examples/stream_chat.py)

Server-side FastAPI proxy example (keeps API keys off the client):

- [`sdk/python/examples/fastapi-proxy/`](https://github.com/chatvector-ai/chatvector-ai/tree/main/sdk/python/examples/fastapi-proxy)

## Error handling

The SDK maps HTTP failures to typed exceptions such as `ChatVectorAuthError`, `ChatVectorRateLimitError`, and `ChatVectorTimeoutError`. See the [README](https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/README.md#error-handling) for the full hierarchy.

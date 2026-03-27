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

The client accepts an optional bearer token for forward compatibility with future authenticated backend deployments:

```python
from chatvector import ChatVectorClient

client = ChatVectorClient(
    base_url="https://api.chatvector.example",
    api_key="your-token",
)
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

## API Notes

The backend currently exposes document upload at `/upload`. The SDK targets `/ingest` as the forward-facing contract and transparently falls back to `/upload` for compatibility with the current repository backend.

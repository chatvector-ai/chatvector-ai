# Getting Started

This guide walks through local setup with Docker, creating an API key, and sending your first chat request.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose
- [Node.js](https://nodejs.org/) and npm (for the frontend demo)
- Either a hosted LLM provider API key (Gemini or OpenAI recommended) or a local [Ollama](https://ollama.com/) installation

## Start the development stack

From the repository root:

```bash
make quickstart
```

The command creates environment files, pauses for provider credentials when needed, installs frontend dependencies, builds the backend Docker image, starts services, and opens browser tabs when ready.

If your provider configuration is already complete, use:

```bash
make
```

Backend-only:

```bash
docker compose up --build
```

## Ollama with Docker

If you use Ollama instead of a hosted API key, run Ollama on your **host** and point the **containerized** API at it:

```env
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Inside the API container, `localhost` is the container, not your machine — `http://localhost:11434` fails. `host.docker.internal` reaches the host. On Linux, `docker-compose.yml` already maps it via `extra_hosts: host.docker.internal:host-gateway` on the `api` service.

Defaults (when unset): **`llama3`** for chat and **`nomic-embed-text`** for embeddings. On the host:

```bash
ollama pull llama3 nomic-embed-text
```

You can instead set `LLM_MODEL` and `EMBEDDING_MODEL` to installed models.

Startup prints **Provider configuration validated** but Ollama has no API key — startup does not test connectivity or whether models are pulled. Wrong URLs tend to show `provider_unreachable` during ingestion; missing models can produce a soft `llm_unexpected` on chat.

For an API process running **on the host** (not in Docker), use `OLLAMA_BASE_URL=http://localhost:11434`.

When the stack is healthy:

| Service | URL |
|---------|-----|
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Frontend demo | http://localhost:3000 |

## Generate an API key

Local development (`APP_ENV=development` or `APP_ENV=test`) bypasses API-key authentication, so you can explore the API without a key.

For production-style auth locally, or before deploying, create a tenant and key with the CLI:

```bash
docker compose exec api python -m backend.cli create-tenant-key \
  --tenant "My Org" \
  --tenant-id my-org
```

The command prints a bearer token once. Store it securely — it cannot be retrieved later.

Use the key on authenticated requests:

```bash
curl -H "Authorization: Bearer cv_live_..." http://localhost:8000/status
```

## What works without extra configuration

Upload a supported file, wait until ingestion is `completed`, and ask a question. Defaults:

- Retrieval is session-scoped and vector-only. Hybrid search, reranking, query rewrite/expand/step-back, the embedding cache, and webhooks stay off.
- Follow-up questions in a session can use recent history. A clearly standalone question does not spend an extra LLM call to rewrite it. If that resolution call fails, chat continues with the original question.
- Supported uploads are PDF, plain text (`.txt`), Markdown (`.md`), HTML (`.html` / `.htm`), and DOCX (`.docx`). Image-only PDFs are not OCR'd. HTML is parsed locally; remote images and scripts are not fetched. PPTX is not supported.

Pass `debug_retrieval: true` on chat when you need the effective query, history decision, timings, and component scores. That flag is diagnostic and does not change the answer path beyond returning the trace.

## First chat flow

=== "curl"

    ```bash
    # 1. Upload a document
    curl -F "file=@handbook.pdf" http://localhost:8000/upload

    # 2. Poll status until completed (replace DOCUMENT_ID)
    curl http://localhost:8000/documents/DOCUMENT_ID/status

    # 3. Ask a question
    curl -X POST http://localhost:8000/chat \
      -H "Content-Type: application/json" \
      -d '{
        "question": "Summarize this document.",
        "doc_id": "DOCUMENT_ID",
        "match_count": 5
      }'
    ```

=== "Python SDK"

    ```python
    from chatvector import ChatVectorClient

    with ChatVectorClient(base_url="http://localhost:8000") as client:
        upload = client.upload_document("handbook.pdf")
        ready = client.wait_for_ready(upload.document_id, timeout=90, interval=3)
        answer = client.chat(
            question="Summarize this document.",
            doc_id=ready.document_id,
            match_count=5,
        )

    print(answer.answer)

    follow_up = client.chat(
        question="What does that section require?",
        doc_id=ready.document_id,
        session_id=answer.session_id,
    )
    print(follow_up.answer)
    ```

=== "TypeScript SDK"

    ```typescript
    import { ChatVectorClient } from "@chatvector/sdk";

    const client = new ChatVectorClient({
      baseUrl: "http://localhost:8000",
    });

    const uploaded = await client.uploadDocument({ path: "./handbook.pdf" });
    await client.waitForReady(uploaded.documentId);
    const answer = await client.chat({
      question: "Summarize this document.",
      docId: uploaded.documentId,
      matchCount: 5,
    });
    const followUp = await client.chat({
      question: "What does that section require?",
      docId: uploaded.documentId,
      sessionId: answer.sessionId,
    });
    console.log(answer.answer, followUp.answer);
    ```

=== "Frontend demo"

    Open http://localhost:3000, upload a PDF, plain-text, Markdown (`.md`), HTML (`.html`/`.htm`), or DOCX (`.docx`) file, wait for ingestion to finish, then ask a question in the chat panel.

## Sessions and retrieval scopes

Chat creates a session when you omit `session_id` and returns it on the response. Pass that id on the next turn. Retrieval history (used to understand a follow-up) and generation history (injected into the answer) are separate windows. Defaults are 6 and 10 recent messages. Requested windows from 0 through 100 are honored; values above 100 are rejected.

Use `scope: "tenant"` to search every document for the tenant instead of the session. Compare-style batch items skip conversational history unless you set `skip_history_transform` to false.

See the [API reference](api-reference.md) for retrieval, history, metadata, replacement, and debug fields.

## Next steps

- Browse the full [API reference](api-reference.md)
- Integrate with the [Python SDK](sdk/python.md) or [TypeScript SDK](sdk/typescript.md)
- Read the [deployment guide](deployment.md) before going to production

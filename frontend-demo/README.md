# ChatVector Frontend Demo

This folder contains the ChatVector frontend demo. It is a Next.js app for trying the local ChatVector flow: upload PDF, text, Markdown, HTML, or DOCX files, watch ingestion progress, chat with retrieved context and citations, run batch queries, and inspect retrieval metadata. It is a contributor demo, not a standalone product. Production apps should keep the API key on a server proxy (`sdk/typescript/examples/next-proxy` or `sdk/python/examples/fastapi-proxy`). The demo's `NEXT_PUBLIC_CHATVECTOR_API_KEY` is only for local experiments against a development backend.

## What the demo includes

| Page | Path | Capabilities |
| --- | --- | --- |
| Chat | `/chat` | Document upload, Postgres-backed session sidebar, retrieval scope/match-count controls, retrieval inspector, cited answers via SSE |
| Batch | `/batch` | Compare and synthesize modes; tenant document list from `GET /documents` |
| Status | `/status` | Live backend health and system metrics |

The header groups **Demo** (Chat, Batch, Status) and **Docs** (Getting Started, Architecture, SDK, Roadmap, Contributing) links.

**Streaming status:** Chat uses `/chat/stream` when `ENABLE_STREAMING=true` on the backend, with automatic fallback to `POST /chat` if streaming is disabled. Ingestion progress uses SSE (`/documents/{id}/status/stream`) with polling fallback. While a document is `queued`, the backend may return `queue_position` (1 = next to process); the demo shows this on attachment chips when position is greater than 1.

**Batch documents:** The batch page loads the tenant document list from `GET /documents` on each visit — not from browser localStorage.

## Prerequisites

- Node.js 18+
- ChatVector backend running at `http://localhost:8000` (see the root [README setup instructions](../README.md))

## Setup

```bash
npm install
cp .env.example .env.local
```

Set the backend URL in `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

For production backends (`APP_ENV=production`), also set an API key:

```env
NEXT_PUBLIC_CHATVECTOR_API_KEY=cv_live_yourprefix.yoursecret
```

## Run

```bash
npm run dev
```

Open http://localhost:3000.

From the repository root, you can also run `make dev` to start the backend stack and frontend dev server together.

## Verify changes

Run these from `frontend-demo/` before opening a PR:

```bash
npm run build
npm run lint
```

## Where to go next

- [DEVELOPMENT.md](../DEVELOPMENT.md) — local development setup, including the Frontend section
- [FRONTEND.md](./FRONTEND.md) — design tokens and UI conventions
- [Issues labeled `frontend-demo`](https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aissue%20is%3Aopen%20label%3Afrontend-demo) — frontend demo work items

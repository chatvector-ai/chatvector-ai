# ChatVector Frontend Demo

This folder contains the ChatVector frontend demo. It is a Next.js app for trying the local ChatVector flow: upload documents, watch ingestion progress, chat with retrieved context and citations, run batch queries, and inspect retrieval metadata. It is a contributor demo, not a standalone product.

## What the demo includes

| Page | Path | Capabilities |
| --- | --- | --- |
| Chat | `/chat` | Document upload, session sidebar, retrieval scope/match-count controls, retrieval inspector, cited answers |
| Batch | `/batch` | Compare and synthesize modes across uploaded documents |
| Status | `/status` | Live backend health and system metrics |

The header groups **Demo** (Chat, Batch, Status) and **Docs** (Getting Started, Architecture, SDK, Roadmap, Contributing) links.

**Streaming status:** ingestion progress uses SSE (`/documents/{id}/status/stream`) with polling fallback. While a document is `queued`, the backend may return `queue_position` (1 = next to process); the demo shows this on attachment chips when position is greater than 1.

Chat in this demo still uses non-streaming `POST /chat` — backend `/chat/stream` and the Python SDK streaming client are available for integrators. The chat UI simulates typing with a character-by-character animation in `MessageList.tsx`; this is **not** real SSE token streaming.

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
NEXT_PUBLIC_API_KEY=cv_live_yourprefix.yoursecret
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

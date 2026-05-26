# ChatVector Frontend Demo

This folder contains the ChatVector frontend demo. It is a Next.js app for trying the local ChatVector flow: upload documents, watch ingestion progress, and chat with retrieved context and citations. It is a contributor demo, not a standalone product.

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

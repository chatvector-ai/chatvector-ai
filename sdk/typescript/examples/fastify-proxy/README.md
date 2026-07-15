# Fastify server-side proxy

This runnable example keeps the ChatVector API key behind a Fastify backend.
It demonstrates the v0 lifecycle:

```text
uploadDocument -> waitForReady -> createSession -> chat
```

`POST /api/documents` performs the first two operations. `POST /api/chat`
creates an explicit session when the caller does not provide one, then sends
the chat request. `GET /api/documents/:id` exposes status checks separately.

> [!WARNING]
> This is a server example, not a browser SDK. `CHATVECTOR_API_KEY` is read
> only by this Node process. Do not expose it in browser JavaScript, public
> environment variables, HTML, JSON responses, logs, or the curl commands
> used by your application's clients.

## Run locally

Build the SDK first, then install the example:

```sh
cd sdk/typescript
npm ci
npm run build

cd examples/fastify-proxy
npm install
cp .env.example .env
```

Fill the two server-only values in `.env`:

```dotenv
CHATVECTOR_BASE_URL=https://your-chatvector-api.example.com
CHATVECTOR_API_KEY=your-server-side-key
```

Start the proxy with Node.js 22 or 24:

```sh
npm start
```

The example listens on `http://localhost:3000` by default. Set `PORT` in the
server environment to change it.

## Application authentication boundary

Every `/api/*` request requires an `x-user-id` header as a short, visible
placeholder for the application's own authentication. It is not sufficient
authentication for production: replace the hook with a verified session or
JWT and enforce document/session ownership in persistent storage.

The application user identity is deliberately separate from ChatVector bearer
authentication. The proxy does not accept a ChatVector key from callers and
does not return its server key in a response.

## Try the flow with curl

Upload a document and wait until ingestion completes:

```sh
curl --fail-with-body --silent --show-error \
  --request POST http://localhost:3000/api/documents \
  --header "x-user-id: user_123" \
  --form "file=@./handbook.pdf;type=application/pdf"
```

The response includes the ready document ID:

```json
{
  "document": {
    "id": "document-id",
    "status": "completed"
  }
}
```

Status can also be checked directly:

```sh
curl --fail-with-body --silent --show-error \
  http://localhost:3000/api/documents/document-id \
  --header "x-user-id: user_123"
```

Ask the first question. With no `sessionId`, the proxy calls
`createSession()` before `chat()` and returns the new ID alongside the answer:

```sh
curl --fail-with-body --silent --show-error \
  --request POST http://localhost:3000/api/chat \
  --header "content-type: application/json" \
  --header "x-user-id: user_123" \
  --data '{"docId":"document-id","question":"Summarize this document."}'
```

Continue the same conversation by sending the returned session ID:

```sh
curl --fail-with-body --silent --show-error \
  --request POST http://localhost:3000/api/chat \
  --header "content-type: application/json" \
  --header "x-user-id: user_123" \
  --data '{"docId":"document-id","sessionId":"session-id","question":"What are the exceptions?"}'
```

## Cancellation and errors

Each route creates an `AbortController` tied to the downstream HTTP
connection. If the caller disconnects before the response finishes, the same
`AbortSignal` cancels the SDK fetch, readiness polling, or retry backoff.

`ChatVectorRateLimitError` becomes HTTP 429 and includes a sanitized
`retryAfterMs` value when available. Other `ChatVectorAPIError` instances are
mapped to a safe proxy response; upstream decoded details, causes, and
credentials remain server-side. Upstream authentication failures are treated
as proxy configuration failures and are not presented as the application's
own 401 response.

The 25 MiB upload limit is an example setting. Adjust it together with your
reverse proxy limits and product policy.

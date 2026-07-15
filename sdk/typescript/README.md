# ChatVector TypeScript SDK

`@chatvector/sdk` is the official, Node-first TypeScript client for the
ChatVector API. It covers document upload and readiness polling,
non-streaming chat, batch chat, and sessions.

> [!WARNING]
> This package is for server-side Node.js applications only. Never put a
> ChatVector API key in browser code, a public environment variable such as
> `NEXT_PUBLIC_*`, local storage, or a response sent to a browser. The browser
> export intentionally throws a server-only usage error; it is a safety guard,
> not a browser SDK.

## Install

```sh
npm install @chatvector/sdk
```

The package is ESM-first and also provides a CommonJS `require` entry point.
The `@chatvector` npm scope must be confirmed by maintainers before the first
public release.

## Quickstart

Create one client when your Node server starts and reuse it for requests:

```ts
import {
  ChatVectorAPIError,
  ChatVectorClient,
  ChatVectorRateLimitError,
} from "@chatvector/sdk";

const client = new ChatVectorClient({
  baseUrl: process.env.CHATVECTOR_BASE_URL!,
  apiKey: process.env.CHATVECTOR_API_KEY!,
  timeoutMs: 30_000,
});

const controller = new AbortController();

try {
  const uploaded = await client.uploadDocument(
    { path: "./documents/handbook.pdf", contentType: "application/pdf" },
    { signal: controller.signal },
  );

  await client.waitForReady(uploaded.documentId, {
    signal: controller.signal,
    timeoutMs: 60_000,
    pollIntervalMs: 2_000,
  });

  // Create the session explicitly when the conversation must continue. The
  // non-streaming chat response does not expose an automatically-created ID.
  const session = await client.createSession(undefined, {
    signal: controller.signal,
  });

  const answer = await client.chat(
    {
      question: "What is the vacation policy?",
      docId: uploaded.documentId,
      sessionId: session.id,
      matchCount: 5,
      scope: "session",
    },
    { signal: controller.signal },
  );

  console.log(answer.answer);
} catch (error) {
  if (error instanceof ChatVectorRateLimitError) {
    console.error("Rate limited; retry after (ms):", error.retryAfterMs);
  } else if (error instanceof ChatVectorAPIError) {
    console.error("ChatVector request failed:", error.kind, error.code);
  } else {
    throw error;
  }
}
```

Uploads also accept replayable in-memory data:

```ts
await client.uploadDocument({
  data: new Uint8Array(buffer),
  fileName: "handbook.pdf",
  contentType: "application/pdf",
});
```

One-shot Node streams are intentionally not accepted because the SDK may need
to replay the body for the `/ingest` to `/upload` compatibility fallback.

## Cancellation

Every network-facing method accepts `{ signal?: AbortSignal }`.
`waitForReady` uses the same signal for active HTTP requests, polling delays,
and retry backoff. Connect this signal to the downstream request lifecycle in
web servers so work stops if the caller disconnects. Caller cancellation is
left as the platform `AbortError`; SDK-created deadlines are reported as
`ChatVectorTimeoutError`.

See the [Fastify server-side proxy](./examples/fastify-proxy/README.md) for a
complete disconnect-aware example.

## Errors

The public error hierarchy is:

- `ChatVectorAuthError` for HTTP 401 and 403.
- `ChatVectorRateLimitError` for HTTP 429. Its `retryAfterMs` field contains a
  valid `Retry-After` value when the server supplied one.
- `ChatVectorTimeoutError` for HTTP 408/504, SDK request deadlines, and
  connection failures.
- `ChatVectorAPIError` for other API, malformed-response, and transport
  failures. A failed ingestion is reported with `code: "document_failed"`
  and the final document status in `details`.

All SDK errors have a stable `kind` discriminator (`api`, `auth`,
`rate_limit`, or `timeout`). Use `isChatVectorError(error)` when code may load
both ESM and CJS copies and `instanceof` alone would be unreliable.

Successful chat and batch responses may contain `status: "error"` for
provider or retrieval soft failures. Those are returned as typed responses;
they are not converted into HTTP exceptions.

The SDK never writes requests, retries, polling events, or errors to the
console, and it never places the bearer token in URLs, response models, error
details, or causes.

## Retry behavior

By default, eligible `GET` and `HEAD` requests are retried at most twice (three
total attempts) for connection/timeouts and HTTP 408, 429, 502, 503, or 504.
Backoff uses bounded exponential full jitter and respects valid delta-seconds
or HTTP-date `Retry-After` headers.

Mutating requests are never automatically replayed. This includes document
uploads, chat, batch chat, session creation, and session deletion. The API has
no idempotency-key contract, so replaying an ambiguous request could duplicate
documents, sessions, or messages.

Configure or disable retry behavior at construction:

```ts
const client = new ChatVectorClient({
  baseUrl: process.env.CHATVECTOR_BASE_URL!,
  apiKey: process.env.CHATVECTOR_API_KEY!,
  retry: {
    maxRetries: 2,
    initialDelayMs: 500,
    maxDelayMs: 8_000,
  },
});

const noRetryClient = new ChatVectorClient({
  baseUrl: process.env.CHATVECTOR_BASE_URL!,
  apiKey: process.env.CHATVECTOR_API_KEY!,
  retry: false,
});
```

## Runtime support

| Runtime | Support |
| --- | --- |
| Node.js 22 LTS | Supported and CI-tested; minimum version |
| Node.js 24 LTS | Supported and CI-tested; preferred LTS |
| Node.js 26 Current | Best effort only until it becomes LTS |
| Node.js 20 and earlier | Unsupported |
| Browsers, React, React Native, Workers, Deno, and Bun | Unsupported |

The package compiles to ES2022, ships TypeScript declarations, and uses native
Node `fetch`, `FormData`, `Blob`, `AbortController`, and filesystem APIs. It
has no runtime dependencies.

## API surface

```ts
client.uploadDocument(input, options?);
client.getDocumentStatus(documentId, options?);
client.waitForReady(documentId, options?);

client.chat(request, options?);
client.batchChat(request, options?);

client.createSession(input?, options?);
client.getSession(sessionId, options?);
client.listSessions(options?);
client.deleteSession(sessionId, options?);
```

Public request and response names use camelCase. The SDK translates them to
the backend's snake_case JSON contract. Response types include an optional
`_raw` payload for forward-compatible access to currently unmodeled fields;
`_raw` is not part of the stable response contract.

Streaming chat, document-status SSE, browser support, pagination helpers, and
logger/telemetry callbacks are outside v0.

## License

MIT

import { describe, expect, it } from "vitest";

import {
  ChatVectorAPIError,
  ChatVectorAuthError,
  ChatVectorClient,
  ChatVectorRateLimitError,
  ChatVectorTimeoutError,
} from "../../src/index.js";
import { DOCUMENT_ID } from "../fixtures/payloads.js";
import {
  captureRejection,
  chunkedSseResponse,
  createFetchMock,
  flushAsyncWork,
  getFetchCall,
  getJsonBody,
  jsonResponse,
  pendingAfterFirstEventSseResponse,
  sseResponse,
} from "../helpers/mock-fetch.js";

const API_KEY = "cv_live_secret_do_not_leak";

function makeClient(fetch: typeof globalThis.fetch): ChatVectorClient {
  return new ChatVectorClient({
    baseUrl: "https://api.chatvector.test",
    apiKey: API_KEY,
    fetch,
    retry: false,
  });
}

const successSse = [
  'event: token',
  'data: "Hello"',
  "",
  'event: token',
  'data: " world"',
  "",
  "event: complete",
  'data: {"session_id":"session-1","sources":[{"file_name":"guide.pdf","page_number":1,"chunk_index":0,"score":0.9,"score_type":"vector"}],"latency_ms":120,"model":"gpt-test"}',
  "",
  "event: done",
  "data: [DONE]",
  "",
].join("\n");

const completePayload = {
  session_id: "session-1",
  sources: [
    {
      file_name: "guide.pdf",
      page_number: 1,
      chunk_index: 0,
      score: 0.9,
      score_type: "vector",
    },
  ],
  latency_ms: 120,
  model: "gpt-test",
};

function encode(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

function splitIntoChunks(text: string, sizes: number[]): Uint8Array[] {
  const bytes = encode(text);
  const chunks: Uint8Array[] = [];
  let offset = 0;
  for (const size of sizes) {
    chunks.push(bytes.slice(offset, offset + size));
    offset += size;
  }
  if (offset < bytes.length) {
    chunks.push(bytes.slice(offset));
  }
  return chunks;
}

describe("streamChat", () => {
  it("posts to /chat/stream and parses token and complete events", async () => {
    const fetch = createFetchMock(sseResponse(successSse));
    const events = [];
    for await (const event of makeClient(fetch).streamChat({
      question: "Summarize this",
      docId: DOCUMENT_ID,
      matchCount: 4,
      sessionId: "session-1",
      scope: "tenant",
    })) {
      events.push(event);
    }

    const { url, init } = getFetchCall(fetch);
    expect(url).toBe("https://api.chatvector.test/chat/stream");
    expect(init.method).toBe("POST");
    expect(getJsonBody(init)).toEqual({
      question: "Summarize this",
      doc_id: DOCUMENT_ID,
      match_count: 4,
      session_id: "session-1",
      scope: "tenant",
    });
    expect(events).toEqual([
      { type: "token", content: "Hello" },
      { type: "token", content: " world" },
      {
        type: "complete",
        sessionId: "session-1",
        sources: [
          {
            fileName: "guide.pdf",
            pageNumber: 1,
            chunkIndex: 0,
            score: 0.9,
            scoreType: "vector",
          },
        ],
        latencyMs: 120,
        model: "gpt-test",
        _raw: completePayload,
      },
    ]);
  });

  it("preserves retrieval_debug on complete events via _raw", async () => {
    const payload = {
      ...completePayload,
      retrieval_debug: { candidates: 8, reranked: true },
    };
    const fetch = createFetchMock(
      sseResponse(
        [
          "event: complete",
          `data: ${JSON.stringify(payload)}`,
          "",
        ].join("\n"),
      ),
    );
    const events = [];
    for await (const event of makeClient(fetch).streamChat({
      question: "Q",
      docId: DOCUMENT_ID,
    })) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      type: "complete",
      sessionId: "session-1",
      latencyMs: 120,
      model: "gpt-test",
      _raw: payload,
    });
    expect(events[0]).toMatchObject({
      _raw: { retrieval_debug: { candidates: 8, reranked: true } },
    });
  });

  it("accepts complete events with and without message_id", async () => {
    const withId = {
      ...completePayload,
      message_id: "asst-msg-9",
    };
    const withoutId = { ...completePayload };

    async function read(payload: Record<string, unknown>) {
      const fetch = createFetchMock(
        sseResponse(
          ["event: complete", `data: ${JSON.stringify(payload)}`, ""].join("\n"),
        ),
      );
      const events = [];
      for await (const event of makeClient(fetch).streamChat({
        question: "Q",
        docId: DOCUMENT_ID,
      })) {
        events.push(event);
      }
      return events;
    }

    const present = await read(withId);
    const absent = await read(withoutId);

    expect(present).toHaveLength(1);
    expect(present[0]).toMatchObject({
      type: "complete",
      messageId: "asst-msg-9",
      sessionId: "session-1",
    });
    expect(absent).toHaveLength(1);
    expect(absent[0]).toMatchObject({
      type: "complete",
      sessionId: "session-1",
    });
    expect(absent[0]).not.toHaveProperty("messageId");
  });

  it("ignores legacy done events", async () => {
    const fetch = createFetchMock(
      sseResponse(['event: done', "data: [DONE]", ""].join("\n")),
    );
    const events = [];
    for await (const event of makeClient(fetch).streamChat({
      question: "Q",
      docId: DOCUMENT_ID,
    })) {
      events.push(event);
    }
    expect(events).toEqual([]);
  });

  it("maps structured stream errors to typed SDK errors", async () => {
    const fetch = createFetchMock(
      sseResponse(
        [
          'event: error',
          'data: {"type":"error","code":"llm_rate_limited","message":"Too many requests"}',
          "",
        ].join("\n"),
      ),
    );
    const error = await captureRejection(
      (async () => {
        for await (const _event of makeClient(fetch).streamChat({
          question: "Q",
          docId: DOCUMENT_ID,
        })) {
          // drain
        }
      })(),
    );
    expect(error).toBeInstanceOf(ChatVectorRateLimitError);
  });

  it("redacts the configured API key from SSE error messages and details", async () => {
    const fetch = createFetchMock(
      sseResponse(
        [
          "event: error",
          `data: {"type":"error","code":"provider_failed","message":"Echoed ${API_KEY}","nested":{"${API_KEY}":"value=${API_KEY}"}}`,
          "",
        ].join("\n"),
      ),
    );
    const error = await captureRejection(
      (async () => {
        for await (const _event of makeClient(fetch).streamChat({
          question: "Q",
          docId: DOCUMENT_ID,
        })) {
          // drain
        }
      })(),
    );
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    const serialized = JSON.stringify({
      message: (error as Error).message,
      details: (error as ChatVectorAPIError).details,
    });
    expect(serialized).not.toContain(API_KEY);
    expect(serialized).toContain("[REDACTED]");
  });

  it.each([
    ["llm_missing_api_key", ChatVectorAuthError],
    ["llm_invalid_api_key", ChatVectorAuthError],
    ["llm_timeout_or_connection", ChatVectorTimeoutError],
    ["provider_failed", ChatVectorAPIError],
  ])("maps stream error code %s", async (code, ErrorClass) => {
    const fetch = createFetchMock(
      sseResponse(
        [
          "event: error",
          `data: {"type":"error","code":"${code}","message":"Stream failed"}`,
          "",
        ].join("\n"),
      ),
    );
    const error = await captureRejection(
      (async () => {
        for await (const _event of makeClient(fetch).streamChat({
          question: "Q",
          docId: DOCUMENT_ID,
        })) {
          // drain
        }
      })(),
    );
    expect(error).toBeInstanceOf(ErrorClass);
  });

  it.each([
    ["token", 'event: token\ndata: not-json\n\n'],
    ["complete", 'event: complete\ndata: {bad json\n\n'],
    ["error", 'event: error\ndata: not-json\n\n'],
  ])("maps malformed %s JSON to ChatVectorAPIError", async (_eventType, sse) => {
    const fetch = createFetchMock(sseResponse(sse));
    const error = await captureRejection(
      (async () => {
        for await (const _event of makeClient(fetch).streamChat({
          question: "Q",
          docId: DOCUMENT_ID,
        })) {
          // drain
        }
      })(),
    );
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect(error).not.toBeInstanceOf(SyntaxError);
    expect((error as ChatVectorAPIError).details).toMatchObject({
      event: _eventType,
    });
  });

  it("maps non-string token JSON to ChatVectorAPIError", async () => {
    const fetch = createFetchMock(sseResponse('event: token\ndata: 1\n\n'));
    const error = await captureRejection(
      (async () => {
        for await (const _event of makeClient(fetch).streamChat({
          question: "Q",
          docId: DOCUMENT_ID,
        })) {
          // drain
        }
      })(),
    );
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect((error as ChatVectorAPIError).details).toMatchObject({
      event: "token",
      payload: 1,
    });
  });

  it("raises HTTP errors before bytes are consumed", async () => {
    const fetch = createFetchMock(
      jsonResponse({ detail: "Streaming disabled" }, { status: 400 }),
    );
    const error = await captureRejection(
      (async () => {
        for await (const _event of makeClient(fetch).streamChat({
          question: "Q",
          docId: DOCUMENT_ID,
        })) {
          // drain
        }
      })(),
    );
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does not replay a retryable response because streaming chat is mutating", async () => {
    const fetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
    );
    await captureRejection(
      (async () => {
        for await (const _event of new ChatVectorClient({
          baseUrl: "https://api.chatvector.test",
          fetch,
          retry: { maxRetries: 5 },
        }).streamChat({ question: "Q", docId: DOCUMENT_ID })) {
          // drain
        }
      })(),
    );
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("honors a pre-aborted signal before opening the stream", async () => {
    const fetch = createFetchMock(sseResponse(successSse));
    const controller = new AbortController();
    controller.abort();
    const error = await captureRejection(
      (async () => {
        for await (const _event of makeClient(fetch).streamChat(
          { question: "Q", docId: DOCUMENT_ID },
          { signal: controller.signal },
        )) {
          // drain
        }
      })(),
    );
    expect(error).toBe(controller.signal.reason);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("aborts between already-buffered events without another fetch", async () => {
    const controller = new AbortController();
    const fetch = createFetchMock((_input, init) => {
      const signal = init?.signal;
      const firstChunk = encode('event: token\ndata: "partial"\n\n');
      const stream = new ReadableStream<Uint8Array>({
        start(streamController) {
          streamController.enqueue(firstChunk);
          if (signal == null) {
            streamController.close();
            return;
          }
          const abortSignal = signal;
          const fail = (): void => {
            streamController.error(
              "reason" in abortSignal
                ? abortSignal.reason
                : new DOMException("The operation was aborted", "AbortError"),
            );
          };
          if (abortSignal.aborted) {
            fail();
            return;
          }
          abortSignal.addEventListener("abort", fail, { once: true });
        },
      });
      return new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    });

    const iterator = makeClient(fetch).streamChat(
      { question: "Q", docId: DOCUMENT_ID },
      { signal: controller.signal },
    )[Symbol.asyncIterator]();

    const first = await iterator.next();
    expect(first.value).toEqual({ type: "token", content: "partial" });
    controller.abort(new DOMException("Caller disconnected", "AbortError"));

    const error = await captureRejection(iterator.next());
    expect(error).toBeInstanceOf(DOMException);
    expect(fetch).toHaveBeenCalledTimes(1);
    await flushAsyncWork();
  });

  it("aborts during a pending stream read without waiting for another event", async () => {
    const controller = new AbortController();
    const firstEvent = encode('event: token\ndata: "partial"\n\n');
    const fetch = createFetchMock(() =>
      pendingAfterFirstEventSseResponse(firstEvent),
    );

    const iterator = makeClient(fetch).streamChat(
      { question: "Q", docId: DOCUMENT_ID },
      { signal: controller.signal },
    )[Symbol.asyncIterator]();

    const first = await iterator.next();
    expect(first.value).toEqual({ type: "token", content: "partial" });

    const pendingRead = iterator.next();
    await flushAsyncWork();
    controller.abort(new DOMException("Caller disconnected", "AbortError"));

    const error = await captureRejection(pendingRead);
    expect(error).toBeInstanceOf(DOMException);
    expect((error as DOMException).message).toBe("Caller disconnected");
    expect(fetch).toHaveBeenCalledTimes(1);
    await flushAsyncWork();
  });

  it("parses fragmented SSE chunks including split JSON and Unicode", async () => {
    const unicodeToken = '"café ☕"';
    const completeJson = JSON.stringify({
      session_id: "session-1",
      sources: [],
      latency_ms: 50,
      model: "gpt-test",
    });
    const sseText = [
      "event: token",
      `data: ${unicodeToken}`,
      "",
      "event: complete",
      `data: ${completeJson}`,
      "",
      "event: done",
      "data: [DONE]",
      "",
    ].join("\n");

    const chunks = splitIntoChunks(sseText, [5, 7, 3, 11, 4, 6, 9, 2, 8, 12]);
    const fetch = createFetchMock(chunkedSseResponse(chunks));
    const events = [];
    for await (const event of makeClient(fetch).streamChat({
      question: "Q",
      docId: DOCUMENT_ID,
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      { type: "token", content: "café ☕" },
      {
        type: "complete",
        sessionId: "session-1",
        sources: [],
        latencyMs: 50,
        model: "gpt-test",
        _raw: JSON.parse(completeJson),
      },
    ]);
  });

  it("parses CRLF-delimited SSE events from chunked bytes", async () => {
    const crlfSse =
      'event: token\r\ndata: "Hi"\r\n\r\n' +
      "event: complete\r\n" +
      'data: {"session_id":null,"sources":[],"latency_ms":1,"model":"m"}\r\n\r\n';
    const fetch = createFetchMock(
      chunkedSseResponse(splitIntoChunks(crlfSse, [10, 14, 6, 20])),
    );
    const events = [];
    for await (const event of makeClient(fetch).streamChat({
      question: "Q",
      docId: DOCUMENT_ID,
    })) {
      events.push(event);
    }
    expect(events).toEqual([
      { type: "token", content: "Hi" },
      {
        type: "complete",
        sessionId: null,
        sources: [],
        latencyMs: 1,
        model: "m",
        _raw: {
          session_id: null,
          sources: [],
          latency_ms: 1,
          model: "m",
        },
      },
    ]);
  });

  it("parses multiple events delivered in one chunk", async () => {
    const combined = encode(
      'event: token\ndata: "A"\n\nevent: token\ndata: "B"\n\n',
    );
    const fetch = createFetchMock(chunkedSseResponse([combined]));
    const events = [];
    for await (const event of makeClient(fetch).streamChat({
      question: "Q",
      docId: DOCUMENT_ID,
    })) {
      events.push(event);
    }
    expect(events).toEqual([
      { type: "token", content: "A" },
      { type: "token", content: "B" },
    ]);
  });

  it("dispatches a trailing partial event without a final blank line", async () => {
    const trailing = encode(
      'event: token\ndata: "tail"\n\nevent: token\ndata: "end"',
    );
    const fetch = createFetchMock(chunkedSseResponse([trailing]));
    const events = [];
    for await (const event of makeClient(fetch).streamChat({
      question: "Q",
      docId: DOCUMENT_ID,
    })) {
      events.push(event);
    }
    expect(events).toEqual([
      { type: "token", content: "tail" },
      { type: "token", content: "end" },
    ]);
  });
});

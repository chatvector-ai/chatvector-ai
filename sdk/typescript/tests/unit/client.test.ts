import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ChatVectorAPIError,
  ChatVectorAuthError,
  ChatVectorClient,
  ChatVectorRateLimitError,
  ChatVectorTimeoutError,
  type ChatVectorClientOptions,
} from "../../src/index.js";
import { DOCUMENT_ID, queuedStatusPayload } from "../fixtures/payloads.js";
import {
  captureRejection,
  createFetchMock,
  flushAsyncWork,
  getFetchCall,
  jsonResponse,
  pendingUntilAborted,
  responseBodyPendingUntilAborted,
  textResponse,
} from "../helpers/mock-fetch.js";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function makeClient(
  fetch: typeof globalThis.fetch,
  extra: Partial<ChatVectorClientOptions> = {},
): ChatVectorClient {
  return new ChatVectorClient({
    baseUrl: "https://api.chatvector.test",
    fetch,
    retry: false,
    ...extra,
  });
}

describe("ChatVectorClient construction and headers", () => {
  it.each([
    "",
    "   ",
    "relative/path",
    "ftp://api.chatvector.test",
    "https://api.chatvector.test?tenant=x",
    "https://api.chatvector.test#fragment",
  ])("rejects invalid base URL %j", (baseUrl) => {
    expect(() => new ChatVectorClient({ baseUrl })).toThrow();
  });

  it("requires an options object", () => {
    expect(() => new ChatVectorClient(undefined as never)).toThrow(TypeError);
    expect(() => new ChatVectorClient(null as never)).toThrow(TypeError);
  });

  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects timeoutMs %s before any request",
    (timeoutMs) => {
      const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
      expect(
        () =>
          new ChatVectorClient({
            baseUrl: "https://api.chatvector.test",
            timeoutMs,
            fetch,
          }),
      ).toThrow(RangeError);
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("rejects a non-string API key", () => {
    expect(
      () =>
        new ChatVectorClient({
          baseUrl: "https://api.chatvector.test",
          apiKey: 123 as never,
        }),
    ).toThrow(TypeError);
  });

  it("normalizes the base URL and injects Accept and bearer auth", async () => {
    const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
    const client = new ChatVectorClient({
      baseUrl: "  https://api.chatvector.test/v1///  ",
      apiKey: "cv_live_secret",
      fetch,
      retry: false,
    });
    await client.getDocumentStatus(DOCUMENT_ID);

    const { url, init } = getFetchCall(fetch);
    const headers = new Headers(init.headers);
    expect(url).toBe(
      `https://api.chatvector.test/v1/documents/${DOCUMENT_ID}/status`,
    );
    expect(init.method).toBe("GET");
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer cv_live_secret");
    expect(headers.has("Content-Type")).toBe(false);
  });

  it.each([undefined, ""])("omits auth for API key %j", async (apiKey) => {
    const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
    const options: ChatVectorClientOptions = {
      baseUrl: "https://api.chatvector.test",
      fetch,
      retry: false,
      ...(apiKey === undefined ? {} : { apiKey }),
    };
    await new ChatVectorClient(options).getDocumentStatus(DOCUMENT_ID);
    expect(
      new Headers(getFetchCall(fetch).init.headers).has("Authorization"),
    ).toBe(false);
  });
});

describe("HTTP error decoding", () => {
  it.each([
    [401, ChatVectorAuthError, "auth"],
    [403, ChatVectorAuthError, "auth"],
    [408, ChatVectorTimeoutError, "timeout"],
    [429, ChatVectorRateLimitError, "rate_limit"],
    [500, ChatVectorAPIError, "api"],
    [504, ChatVectorTimeoutError, "timeout"],
  ] as const)(
    "maps HTTP %i to its typed error",
    async (status, ErrorClass, kind) => {
      const body = {
        detail: { code: `code_${status}`, message: `message_${status}` },
      };
      const fetch = createFetchMock(
        jsonResponse(body, {
          status,
          ...(status === 429 ? { headers: { "Retry-After": "2" } } : {}),
        }),
      );
      const error = await captureRejection(
        makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
      );

      expect(error).toBeInstanceOf(ErrorClass);
      expect(error).toMatchObject({
        statusCode: status,
        code: `code_${status}`,
        message: `message_${status}`,
        kind,
        details: body,
      });
      if (status === 429) {
        expect((error as ChatVectorRateLimitError).retryAfterMs).toBe(2_000);
      }
    },
  );

  it("decodes string detail and preserves the full body", async () => {
    const body = { detail: "Session not found" };
    const fetch = createFetchMock(jsonResponse(body, { status: 404 }));
    const error = await captureRejection(
      makeClient(fetch).getSession("missing"),
    );
    expect(error).toMatchObject({
      message: "Session not found",
      statusCode: 404,
      details: body,
    });
  });

  it("preserves legacy array detail with a safe fallback message", async () => {
    const body = {
      detail: [
        { loc: ["body", "scope"], msg: "invalid retrieval scope" },
      ],
    };
    const fetch = createFetchMock(jsonResponse(body, { status: 422 }));
    const error = await captureRejection(
      makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
    );
    expect(error).toMatchObject({
      message: "ChatVector returned HTTP 422.",
      statusCode: 422,
      details: body,
    });
  });

  it("uses non-JSON error text without treating it as details", async () => {
    const fetch = createFetchMock(
      textResponse("gateway exploded", { status: 502 }),
    );
    const error = await captureRejection(
      makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
    );
    expect(error).toMatchObject({
      message: "gateway exploded",
      statusCode: 502,
      details: undefined,
    });
  });

  it("redacts an API key from messages, values, and object keys", async () => {
    const apiKey = "cv_live_do_not_leak";
    const body = {
      detail: {
        code: "echoed_secret",
        message: `provider echoed ${apiKey}`,
        nested: { [apiKey]: `value=${apiKey}` },
      },
    };
    const fetch = createFetchMock(jsonResponse(body, { status: 500 }));
    const error = await captureRejection(
      makeClient(fetch, { apiKey }).getDocumentStatus(DOCUMENT_ID),
    );
    const serialized = JSON.stringify({
      message: (error as Error).message,
      details: (error as ChatVectorAPIError).details,
    });
    expect(serialized).not.toContain(apiKey);
    expect(serialized).toContain("[REDACTED]");
  });
});

describe("successful response validation and transport failures", () => {
  it("rejects non-JSON success responses", async () => {
    const fetch = createFetchMock(textResponse("<html>oops</html>"));
    const error = await captureRejection(
      makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
    );
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect((error as Error).message).toContain("non-JSON");
  });

  it("rejects a JSON success response that is not an object", async () => {
    const fetch = createFetchMock(jsonResponse([queuedStatusPayload]));
    const error = await captureRejection(
      makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
    );
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect(error).toMatchObject({
      message: "ChatVector returned an unexpected response shape.",
      details: [queuedStatusPayload],
    });
  });

  it("redacts successful raw payloads as a last-resort key safety guard", async () => {
    const apiKey = "cv_live_secret";
    const payload = {
      ...queuedStatusPayload,
      [apiKey]: { echoed: apiKey },
    };
    const fetch = createFetchMock(jsonResponse(payload));
    const result = await makeClient(fetch, { apiKey }).getDocumentStatus(
      DOCUMENT_ID,
    );
    expect(JSON.stringify(result._raw)).not.toContain(apiKey);
  });

  it("maps connection-like TypeErrors to timeout errors", async () => {
    const fetch = createFetchMock(new TypeError("fetch failed"));
    const error = await captureRejection(
      makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
    );
    expect(error).toBeInstanceOf(ChatVectorTimeoutError);
  });

  it.each(["ECONNRESET", "ENOTFOUND", "EAI_AGAIN"])(
    "maps connection error code %s to a timeout error",
    async (code) => {
      const transportError = Object.assign(new Error("connection failed"), {
        code,
      });
      const fetch = createFetchMock(transportError);
      const error = await captureRejection(
        makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
      );
      expect(error).toBeInstanceOf(ChatVectorTimeoutError);
    },
  );

  it("maps unexpected transport failures to the base API error", async () => {
    const fetch = createFetchMock(new Error("unexpected low-level detail"));
    const error = await captureRejection(
      makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
    );
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect(error).not.toBeInstanceOf(ChatVectorTimeoutError);
    expect(error).toMatchObject({ details: { error: "Error" } });
    expect(JSON.stringify(error)).not.toContain("unexpected low-level detail");
  });

  it("maps a response-body transport failure to a typed timeout error", async () => {
    const brokenBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(new TypeError("terminated"));
      },
    });
    const fetch = createFetchMock(
      new Response(brokenBody, {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const error = await captureRejection(
      makeClient(fetch).getDocumentStatus(DOCUMENT_ID),
    );
    expect(error).toBeInstanceOf(ChatVectorTimeoutError);
  });

  it("applies the request deadline while consuming a stalled body", async () => {
    vi.useFakeTimers();
    const fetch = createFetchMock(responseBodyPendingUntilAborted);
    const promise = makeClient(fetch, { timeoutMs: 25 }).getDocumentStatus(
      DOCUMENT_ID,
    );
    const rejection = captureRejection(promise);
    await flushAsyncWork();
    await vi.advanceTimersByTimeAsync(25);
    expect(await rejection).toBeInstanceOf(ChatVectorTimeoutError);
  });
});

describe("caller cancellation", () => {
  const cancellableCalls: Array<
    [
      string,
      (client: ChatVectorClient, signal: AbortSignal) => Promise<unknown>,
    ]
  > = [
    [
      "uploadDocument",
      (client, signal) =>
        client.uploadDocument(
          { data: new Uint8Array([1]), fileName: "notes.txt" },
          { signal },
        ),
    ],
    [
      "getDocumentStatus",
      (client, signal) => client.getDocumentStatus(DOCUMENT_ID, { signal }),
    ],
    [
      "waitForReady",
      (client, signal) => client.waitForReady(DOCUMENT_ID, { signal }),
    ],
    [
      "chat",
      (client, signal) =>
        client.chat({ question: "Question?", docId: DOCUMENT_ID }, { signal }),
    ],
    [
      "batchChat",
      (client, signal) =>
        client.batchChat(
          { queries: [{ question: "Question?", docIds: [DOCUMENT_ID] }] },
          { signal },
        ),
    ],
    [
      "createSession",
      (client, signal) => client.createSession(undefined, { signal }),
    ],
    ["getSession", (client, signal) => client.getSession("session-1", { signal })],
    ["listSessions", (client, signal) => client.listSessions({ signal })],
    [
      "deleteSession",
      (client, signal) => client.deleteSession("session-1", { signal }),
    ],
  ];

  it.each(cancellableCalls)(
    "honors a pre-aborted signal for %s",
    async (_name, invoke) => {
      const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
      const controller = new AbortController();
      controller.abort();
      const error = await captureRejection(
        invoke(makeClient(fetch), controller.signal),
      );
      expect(error).toBe(controller.signal.reason);
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("preserves AbortError during an active fetch and issues no extra request", async () => {
    const fetch = createFetchMock(pendingUntilAborted);
    const controller = new AbortController();
    const promise = makeClient(fetch).getDocumentStatus(DOCUMENT_ID, {
      signal: controller.signal,
    });
    await flushAsyncWork();
    controller.abort();
    expect(await captureRejection(promise)).toBe(controller.signal.reason);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("preserves cancellation while consuming response bytes", async () => {
    const fetch = createFetchMock(responseBodyPendingUntilAborted);
    const controller = new AbortController();
    const promise = makeClient(fetch).getDocumentStatus(DOCUMENT_ID, {
      signal: controller.signal,
    });
    await flushAsyncWork();
    controller.abort();
    expect(await captureRejection(promise)).toBe(controller.signal.reason);
  });

  it("preserves an explicit null abort reason", async () => {
    const fetch = createFetchMock(pendingUntilAborted);
    const controller = new AbortController();
    const promise = makeClient(fetch).getDocumentStatus(DOCUMENT_ID, {
      signal: controller.signal,
    });
    await flushAsyncWork();
    controller.abort(null);
    expect(await captureRejection(promise)).toBeNull();
  });

  it("does not call fetch for a pre-aborted request", async () => {
    const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
    const controller = new AbortController();
    controller.abort();
    const error = await captureRejection(
      makeClient(fetch).getDocumentStatus(DOCUMENT_ID, {
        signal: controller.signal,
      }),
    );
    expect(error).toBe(controller.signal.reason);
    expect(fetch).not.toHaveBeenCalled();
  });
});

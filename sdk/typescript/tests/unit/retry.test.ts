import { describe, expect, it } from "vitest";

import {
  ChatVectorAPIError,
  ChatVectorClient,
  ChatVectorRateLimitError,
  ChatVectorTimeoutError,
  type ChatVectorClientOptions,
} from "../../src/index.js";
import {
  DEFAULT_RETRY_OPTIONS,
  RETRYABLE_STATUS_CODES,
  calculateRetryDelayMs,
  isRetryableMethod,
  isRetryableStatus,
  parseRetryAfter,
  resolveRetryOptions,
} from "../../src/internal/retry.js";
import type { Clock } from "../../src/internal/time.js";
import { DOCUMENT_ID, queuedStatusPayload } from "../fixtures/payloads.js";
import { createAdvancingClock } from "../helpers/clock.js";
import {
  captureRejection,
  createFetchMock,
  jsonResponse,
} from "../helpers/mock-fetch.js";

describe("retry option validation", () => {
  it("uses the approved defaults", () => {
    expect(resolveRetryOptions(undefined)).toEqual({
      maxRetries: 2,
      initialDelayMs: 500,
      maxDelayMs: 8_000,
    });
    expect(DEFAULT_RETRY_OPTIONS).toEqual(resolveRetryOptions(undefined));
  });

  it("merges partial options and disables retries with false", () => {
    expect(resolveRetryOptions({ maxRetries: 4 })).toEqual({
      maxRetries: 4,
      initialDelayMs: 500,
      maxDelayMs: 8_000,
    });
    expect(resolveRetryOptions(false)).toEqual({
      maxRetries: 0,
      initialDelayMs: 500,
      maxDelayMs: 8_000,
    });
    expect(
      resolveRetryOptions({ maxRetries: 0, initialDelayMs: 0, maxDelayMs: 0 }),
    ).toEqual({ maxRetries: 0, initialDelayMs: 0, maxDelayMs: 0 });
  });

  it.each([-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects invalid maxRetries %s",
    (maxRetries) => {
      expect(() => resolveRetryOptions({ maxRetries })).toThrow(RangeError);
    },
  );

  it.each([
    ["initialDelayMs", -1],
    ["initialDelayMs", Number.NaN],
    ["maxDelayMs", -1],
    ["maxDelayMs", Number.POSITIVE_INFINITY],
  ] as const)("rejects invalid %s", (name, value) => {
    expect(() => resolveRetryOptions({ [name]: value })).toThrow(RangeError);
  });
});

describe("retry classification", () => {
  it.each(["GET", "get", "HEAD", "head"])(
    "allows safe method %s",
    (method) => expect(isRetryableMethod(method)).toBe(true),
  );

  it.each(["POST", "DELETE", "PUT", "PATCH", " GET "])(
    "does not replay method %s",
    (method) => expect(isRetryableMethod(method)).toBe(false),
  );

  it("matches the exact approved status set", () => {
    expect([...RETRYABLE_STATUS_CODES]).toEqual([408, 429, 502, 503, 504]);
    for (const status of [408, 429, 502, 503, 504]) {
      expect(isRetryableStatus(status)).toBe(true);
    }
    for (const status of [400, 401, 403, 422, 500, 505]) {
      expect(isRetryableStatus(status)).toBe(false);
    }
  });
});

describe("Retry-After parsing", () => {
  const now = Date.UTC(2026, 6, 14, 12, 0, 0);

  it.each([
    [null, undefined],
    [undefined, undefined],
    ["", undefined],
    ["invalid", undefined],
    ["1.5", undefined],
    ["0", 0],
    [" 2 ", 2_000],
  ] as const)("parses %s", (value, expected) => {
    expect(parseRetryAfter(value, now)).toBe(expected);
  });

  it("parses a future HTTP date and ignores expired dates", () => {
    expect(parseRetryAfter(new Date(now + 3_000).toUTCString(), now)).toBe(
      3_000,
    );
    expect(parseRetryAfter(new Date(now).toUTCString(), now)).toBeUndefined();
    expect(
      parseRetryAfter(new Date(now - 1_000).toUTCString(), now),
    ).toBeUndefined();
  });

  it("ignores delta seconds that cannot be represented safely in milliseconds", () => {
    expect(parseRetryAfter("999999999999999999999", now)).toBeUndefined();
  });
});

describe("full-jitter delay calculation", () => {
  const options = resolveRetryOptions(undefined);

  it("uses exponential bounds and the configured cap", () => {
    expect(calculateRetryDelayMs(0, options, undefined, () => 0)).toBe(0);
    expect(calculateRetryDelayMs(0, options, undefined, () => 0.5)).toBe(250);
    expect(calculateRetryDelayMs(1, options, undefined, () => 1)).toBe(1_000);
    expect(calculateRetryDelayMs(10, options, undefined, () => 1)).toBe(8_000);
  });

  it("uses Retry-After as a floor even above the jitter cap", () => {
    expect(calculateRetryDelayMs(0, options, 300, () => 0.5)).toBe(300);
    expect(calculateRetryDelayMs(10, options, 30_000, () => 1)).toBe(30_000);
  });

  it.each([-1, 1.1, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects random output %s",
    (randomValue) => {
      expect(() =>
        calculateRetryDelayMs(0, options, undefined, () => randomValue),
      ).toThrow(RangeError);
    },
  );

  it("rejects invalid retry indexes and Retry-After values", () => {
    expect(() => calculateRetryDelayMs(-1, options)).toThrow(RangeError);
    expect(() => calculateRetryDelayMs(0, options, -1)).toThrow(RangeError);
  });
});

describe("HTTP retry orchestration", () => {
  function makeClient(
    fetch: typeof globalThis.fetch,
    clock: Clock,
    extra: Partial<ChatVectorClientOptions> = {},
  ): ChatVectorClient {
    const options: ChatVectorClientOptions & {
      __clock: Clock;
      __random: () => number;
    } = {
      baseUrl: "https://api.chatvector.test",
      fetch,
      __clock: clock,
      __random: () => 1,
      ...extra,
    };
    return new ChatVectorClient(options);
  }

  it("retries a GET at most twice and then succeeds", async () => {
    const fetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
      jsonResponse({ detail: "busy" }, { status: 503 }),
      jsonResponse(queuedStatusPayload),
    );
    const { clock, sleeps } = createAdvancingClock();
    const result = await makeClient(fetch, clock).getDocumentStatus(DOCUMENT_ID);

    expect(result.status).toBe("queued");
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(sleeps).toEqual([500, 1_000]);
  });

  it("honors retry:false", async () => {
    const fetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
    );
    const { clock, sleeps } = createAdvancingClock();
    const error = await captureRejection(
      makeClient(fetch, clock, { retry: false }).getDocumentStatus(DOCUMENT_ID),
    );

    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(sleeps).toEqual([]);
  });

  it.each([
    [408, ChatVectorTimeoutError, "timeout"],
    [429, ChatVectorRateLimitError, "rate_limit"],
    [502, ChatVectorAPIError, "api"],
    [503, ChatVectorAPIError, "api"],
    [504, ChatVectorTimeoutError, "timeout"],
  ] as const)(
    "maps final retryable HTTP %i after three total attempts",
    async (status, ErrorClass, kind) => {
      const responses = Array.from({ length: 3 }, () =>
        jsonResponse(
          { detail: { code: `code_${status}`, message: "failed" } },
          { status },
        ),
      );
      const fetch = createFetchMock(...responses);
      const { clock } = createAdvancingClock();
      const error = await captureRejection(
        makeClient(fetch, clock).getDocumentStatus(DOCUMENT_ID),
      );

      expect(error).toBeInstanceOf(ErrorClass);
      expect(error).toMatchObject({ statusCode: status, kind });
      expect(fetch).toHaveBeenCalledTimes(3);
    },
  );

  it("retries connection failures for GET and returns a timeout error", async () => {
    const fetch = createFetchMock(
      new TypeError("fetch failed"),
      new TypeError("fetch failed"),
      new TypeError("fetch failed"),
    );
    const { clock, sleeps } = createAdvancingClock();
    const error = await captureRejection(
      makeClient(fetch, clock).getDocumentStatus(DOCUMENT_ID),
    );

    expect(error).toBeInstanceOf(ChatVectorTimeoutError);
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(sleeps).toEqual([500, 1_000]);
  });

  it("does not retry generic 500 or an unsafe POST", async () => {
    const getFetch = createFetchMock(
      jsonResponse({ detail: "server error" }, { status: 500 }),
    );
    const postFetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
    );
    const getClock = createAdvancingClock();
    const postClock = createAdvancingClock();

    await captureRejection(
      makeClient(getFetch, getClock.clock).getDocumentStatus(DOCUMENT_ID),
    );
    await captureRejection(
      makeClient(postFetch, postClock.clock).chat({
        question: "Question?",
        docId: DOCUMENT_ID,
      }),
    );

    expect(getFetch).toHaveBeenCalledTimes(1);
    expect(postFetch).toHaveBeenCalledTimes(1);
    expect(getClock.sleeps).toEqual([]);
    expect(postClock.sleeps).toEqual([]);
  });

  it("applies Retry-After to sleeps and exposes it on the final 429", async () => {
    const responses = Array.from({ length: 3 }, () =>
      jsonResponse(
        { detail: { code: "rate_limited", message: "Slow down" } },
        { status: 429, headers: { "Retry-After": "2" } },
      ),
    );
    const fetch = createFetchMock(...responses);
    const { clock, sleeps } = createAdvancingClock();
    const error = await captureRejection(
      makeClient(fetch, clock).getDocumentStatus(DOCUMENT_ID),
    );

    expect(sleeps).toEqual([2_000, 2_000]);
    expect(error).toBeInstanceOf(ChatVectorRateLimitError);
    expect((error as ChatVectorRateLimitError).retryAfterMs).toBe(2_000);
  });
});

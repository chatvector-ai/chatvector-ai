import { describe, expect, it, vi } from "vitest";

import {
  ChatVectorAPIError,
  ChatVectorClient,
  ChatVectorTimeoutError,
  type ChatVectorClientOptions,
} from "../../src/index.js";
import type { Clock } from "../../src/internal/time.js";
import {
  DOCUMENT_ID,
  completedStatusPayload,
  failedStatusPayload,
  queuedStatusPayload,
} from "../fixtures/payloads.js";
import {
  createAdvancingClock,
  createBlockingClock,
} from "../helpers/clock.js";
import {
  captureRejection,
  createFetchMock,
  flushAsyncWork,
  getFetchCall,
  jsonResponse,
  pendingUntilAborted,
} from "../helpers/mock-fetch.js";

function makeClient(
  fetch: typeof globalThis.fetch,
  clock?: Clock,
): ChatVectorClient {
  const options: ChatVectorClientOptions & { __clock?: Clock; __random: () => number } = {
    baseUrl: "https://api.chatvector.test",
    fetch,
    __random: () => 1,
    ...(clock === undefined ? {} : { __clock: clock }),
  };
  return new ChatVectorClient(options);
}

describe("getDocumentStatus", () => {
  it("maps all live status fields and preserves unknown raw fields", async () => {
    const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
    const result = await makeClient(fetch).getDocumentStatus(DOCUMENT_ID);
    expect(result).toEqual({
      documentId: DOCUMENT_ID,
      status: "queued",
      chunks: { total: 0, processed: 0 },
      createdAt: "2026-07-14 10:00:00",
      updatedAt: "2026-07-14 10:00:01",
      queuePosition: 2,
      _raw: queuedStatusPayload,
    });
  });

  it("retains explicit null status fields", async () => {
    const payload = {
      document_id: DOCUMENT_ID,
      status: "extracting",
      chunks: null,
      created_at: null,
      updated_at: null,
      error: null,
    };
    const result = await makeClient(
      createFetchMock(jsonResponse(payload)),
    ).getDocumentStatus(DOCUMENT_ID);
    expect(result).toMatchObject({
      chunks: null,
      createdAt: null,
      updatedAt: null,
      error: null,
    });
  });

  it("URL-encodes the document ID", async () => {
    const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
    await makeClient(fetch).getDocumentStatus("document/with space");
    expect(getFetchCall(fetch).url).toBe(
      "https://api.chatvector.test/documents/document%2Fwith%20space/status",
    );
  });

  it("rejects an empty ID before fetch", async () => {
    const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
    await expect(makeClient(fetch).getDocumentStatus("")).rejects.toBeInstanceOf(
      TypeError,
    );
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("waitForReady", () => {
  it("returns immediately when the first status is completed", async () => {
    const fetch = createFetchMock(jsonResponse(completedStatusPayload));
    const { clock, sleeps } = createAdvancingClock();
    const result = await makeClient(fetch, clock).waitForReady(DOCUMENT_ID);
    expect(result.status).toBe("completed");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(sleeps).toEqual([]);
  });

  it("uses the default two-second polling interval", async () => {
    const fetch = createFetchMock(
      jsonResponse(queuedStatusPayload),
      jsonResponse(completedStatusPayload),
    );
    const { clock, sleeps } = createAdvancingClock();
    const result = await makeClient(fetch, clock).waitForReady(DOCUMENT_ID);
    expect(result.status).toBe("completed");
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(sleeps).toEqual([2_000]);
  });

  it("honors a custom polling interval", async () => {
    const embedding = { ...queuedStatusPayload, status: "embedding" };
    const fetch = createFetchMock(
      jsonResponse(queuedStatusPayload),
      jsonResponse(embedding),
      jsonResponse(completedStatusPayload),
    );
    const { clock, sleeps } = createAdvancingClock();
    await makeClient(fetch, clock).waitForReady(DOCUMENT_ID, {
      timeoutMs: 10_000,
      pollIntervalMs: 250,
    });
    expect(sleeps).toEqual([250, 250]);
  });

  it("throws document_failed with the final mapped status", async () => {
    const fetch = createFetchMock(jsonResponse(failedStatusPayload));
    const { clock } = createAdvancingClock();
    const error = await captureRejection(
      makeClient(fetch, clock).waitForReady(DOCUMENT_ID),
    );
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect(error).not.toBeInstanceOf(ChatVectorTimeoutError);
    expect(error).toMatchObject({
      code: "document_failed",
      details: expect.objectContaining({
        documentId: DOCUMENT_ID,
        status: "failed",
        error: failedStatusPayload.error,
      }),
    });
    expect((error as Error).message).toContain(
      failedStatusPayload.error.message,
    );
  });

  it("times out at the injected-clock deadline without issuing another GET", async () => {
    const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
    const { clock, sleeps } = createAdvancingClock();
    const error = await captureRejection(
      makeClient(fetch, clock).waitForReady(DOCUMENT_ID, {
        timeoutMs: 1_000,
        pollIntervalMs: 2_000,
      }),
    );
    expect(error).toBeInstanceOf(ChatVectorTimeoutError);
    expect(error).toMatchObject({
      statusCode: 408,
      details: expect.objectContaining({ status: "queued" }),
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(sleeps).toEqual([1_000]);
  });

  it("times out during an active status fetch without issuing another GET", async () => {
    vi.useFakeTimers();
    const fetch = createFetchMock(pendingUntilAborted);
    const promise = makeClient(fetch).waitForReady(DOCUMENT_ID, {
      timeoutMs: 25,
      pollIntervalMs: 5,
    });
    const rejection = captureRejection(promise);
    await flushAsyncWork();
    await vi.advanceTimersByTimeAsync(25);
    expect(await rejection).toBeInstanceOf(ChatVectorTimeoutError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    [{ timeoutMs: 0 }, "timeoutMs"],
    [{ timeoutMs: Number.NaN }, "timeoutMs"],
    [{ pollIntervalMs: 0 }, "pollIntervalMs"],
    [{ pollIntervalMs: Number.POSITIVE_INFINITY }, "pollIntervalMs"],
  ])("validates wait options before fetch", async (options, field) => {
    const fetch = createFetchMock(jsonResponse(completedStatusPayload));
    const error = await captureRejection(
      makeClient(fetch).waitForReady(DOCUMENT_ID, options),
    );
    expect(error).toBeInstanceOf(RangeError);
    expect((error as Error).message).toContain(field);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("aborts an active status fetch without another request", async () => {
    const fetch = createFetchMock(pendingUntilAborted);
    const controller = new AbortController();
    const promise = makeClient(fetch).waitForReady(DOCUMENT_ID, {
      signal: controller.signal,
    });
    await flushAsyncWork();
    controller.abort();
    expect(await captureRejection(promise)).toBe(controller.signal.reason);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("aborts polling sleep without beginning the next status request", async () => {
    const fetch = createFetchMock(jsonResponse(queuedStatusPayload));
    const { clock, sleepMock } = createBlockingClock();
    const controller = new AbortController();
    const promise = makeClient(fetch, clock).waitForReady(DOCUMENT_ID, {
      signal: controller.signal,
    });
    await vi.waitFor(() => expect(sleepMock).toHaveBeenCalledTimes(1));
    controller.abort();
    expect(await captureRejection(promise)).toBe(controller.signal.reason);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("aborts retry backoff without issuing another GET", async () => {
    const fetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
    );
    const { clock, sleepMock } = createBlockingClock();
    const controller = new AbortController();
    const promise = makeClient(fetch, clock).waitForReady(DOCUMENT_ID, {
      signal: controller.signal,
    });
    await vi.waitFor(() => expect(sleepMock).toHaveBeenCalledTimes(1));
    controller.abort();
    expect(await captureRejection(promise)).toBe(controller.signal.reason);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

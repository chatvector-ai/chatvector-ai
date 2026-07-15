import { describe, expect, it } from "vitest";

import { ChatVectorClient } from "../../src/index.js";
import {
  DOCUMENT_ID,
  SECOND_DOCUMENT_ID,
  batchPartialPayload,
  chatOkPayload,
  chatSoftErrorPayload,
} from "../fixtures/payloads.js";
import {
  captureRejection,
  createFetchMock,
  getFetchCall,
  getJsonBody,
  jsonResponse,
} from "../helpers/mock-fetch.js";

function makeClient(fetch: typeof globalThis.fetch): ChatVectorClient {
  return new ChatVectorClient({
    baseUrl: "https://api.chatvector.test",
    apiKey: "test-key",
    fetch,
    retry: false,
  });
}

describe("chat", () => {
  it("serializes every option to snake_case and maps a complete response", async () => {
    const fetch = createFetchMock(jsonResponse(chatOkPayload));
    const result = await makeClient(fetch).chat({
      question: chatOkPayload.question,
      docId: DOCUMENT_ID,
      matchCount: 7,
      sessionId: "session-1",
      scope: "tenant",
    });

    const { url, init } = getFetchCall(fetch);
    expect(url).toBe("https://api.chatvector.test/chat");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe(
      "application/json",
    );
    expect(getJsonBody(init)).toEqual({
      question: chatOkPayload.question,
      doc_id: DOCUMENT_ID,
      match_count: 7,
      session_id: "session-1",
      scope: "tenant",
    });
    expect(result).toMatchObject({
      question: chatOkPayload.question,
      docId: DOCUMENT_ID,
      chunks: 2,
      answer: "It is an onboarding guide.",
      latencyMs: 312,
      model: "gpt-test",
      status: "ok",
    });
    expect(result.sources).toEqual([
      {
        fileName: "guide.pdf",
        pageNumber: 1,
        chunkIndex: 0,
        score: 0.95,
        scoreType: "hybrid_rrf",
      },
      {
        fileName: null,
        pageNumber: null,
        chunkIndex: null,
        score: null,
        scoreType: null,
      },
    ]);
    expect(result._raw).toEqual(chatOkPayload);
    expect(result._raw).toHaveProperty("retrieval_debug", { candidates: 8 });
  });

  it("omits optional request fields instead of inventing defaults", async () => {
    const fetch = createFetchMock(jsonResponse(chatOkPayload));
    await makeClient(fetch).chat({
      question: chatOkPayload.question,
      docId: DOCUMENT_ID,
    });
    expect(getJsonBody(getFetchCall(fetch).init)).toEqual({
      question: chatOkPayload.question,
      doc_id: DOCUMENT_ID,
    });
  });

  it("returns HTTP-200 soft errors as typed responses", async () => {
    const fetch = createFetchMock(jsonResponse(chatSoftErrorPayload));
    const result = await makeClient(fetch).chat({
      question: chatSoftErrorPayload.question,
      docId: DOCUMENT_ID,
    });
    expect(result.status).toBe("error");
    expect(result.error).toEqual(chatSoftErrorPayload.error);
    expect(result.answer).toBe("");
    expect(result._raw).toEqual(chatSoftErrorPayload);
  });

  it("uses safe mapping defaults for malformed optional backend fields", async () => {
    const payload = {
      question: chatOkPayload.question,
      doc_id: DOCUMENT_ID,
      chunks: "two",
      answer: null,
      sources: [{ file_name: 1, page_number: "1", chunk_index: null }],
      latency_ms: Number.POSITIVE_INFINITY,
      model: null,
      status: "future-status",
    };
    const result = await makeClient(
      createFetchMock(jsonResponse(payload)),
    ).chat({ question: chatOkPayload.question, docId: DOCUMENT_ID });
    expect(result).toMatchObject({
      chunks: 0,
      answer: "",
      latencyMs: 0,
      model: "",
      status: "ok",
      sources: [{ fileName: null, pageNumber: null, chunkIndex: null }],
    });
  });

  it.each([
    [null, "question"],
    [{ question: "", docId: DOCUMENT_ID }, "question"],
    [{ question: "Q", docId: "" }, "docId"],
  ])("rejects invalid input before fetch", async (request, field) => {
    const fetch = createFetchMock(jsonResponse(chatOkPayload));
    const error = await captureRejection(
      makeClient(fetch).chat(request as never),
    );
    expect(error).toBeInstanceOf(TypeError);
    expect((error as Error).message).toContain(field);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not replay a retryable response because chat is mutating", async () => {
    const fetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
    );
    await captureRejection(
      new ChatVectorClient({
        baseUrl: "https://api.chatvector.test",
        fetch,
        retry: { maxRetries: 5 },
      }).chat({ question: "Q", docId: DOCUMENT_ID }),
    );
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("batchChat", () => {
  it("serializes batch- and item-level sessions/scopes", async () => {
    const fetch = createFetchMock(jsonResponse(batchPartialPayload));
    const result = await makeClient(fetch).batchChat({
      queries: [
        {
          question: "Summarize it.",
          docIds: [DOCUMENT_ID],
          matchCount: 3,
          sessionId: "item-session",
          scope: "tenant",
        },
        { question: "What failed?", docIds: [SECOND_DOCUMENT_ID] },
      ],
      sessionId: "batch-session",
      scope: "session",
    });

    expect(getFetchCall(fetch).url).toBe(
      "https://api.chatvector.test/chat/batch",
    );
    expect(getJsonBody(getFetchCall(fetch).init)).toEqual({
      queries: [
        {
          question: "Summarize it.",
          doc_ids: [DOCUMENT_ID],
          match_count: 3,
          session_id: "item-session",
          scope: "tenant",
        },
        { question: "What failed?", doc_ids: [SECOND_DOCUMENT_ID] },
      ],
      session_id: "batch-session",
      scope: "session",
    });
    expect(result).toMatchObject({
      count: 2,
      successCount: 1,
      failureCount: 1,
    });
    expect(result.results[0]).toMatchObject({
      status: "ok",
      docIds: [DOCUMENT_ID],
      answer: "Summary",
      latencyMs: 123,
      model: "gpt-test",
    });
    expect(result.results[0]?._raw).toHaveProperty(
      "session_id",
      "generated-session-kept-in-raw",
    );
    expect(result.results[1]).toEqual(
      expect.objectContaining({
        status: "error",
        docIds: [SECOND_DOCUMENT_ID],
        chunks: 0,
        latencyMs: 0,
        model: "",
        error: batchPartialPayload.results[1]?.error,
        _raw: batchPartialPayload.results[1],
      }),
    );
    expect(result.results[1]).not.toHaveProperty("answer");
    expect(result.results[1]).not.toHaveProperty("sources");
    expect(result._raw).toEqual(batchPartialPayload);
  });

  it("sends an empty batch without adding client-side backend limits", async () => {
    const payload = {
      count: 0,
      success_count: 0,
      failure_count: 0,
      results: [],
    };
    const fetch = createFetchMock(jsonResponse(payload));
    const result = await makeClient(fetch).batchChat({ queries: [] });
    expect(getJsonBody(getFetchCall(fetch).init)).toEqual({ queries: [] });
    expect(result.results).toEqual([]);
  });

  it("does not replay a retryable response because batch chat is mutating", async () => {
    const fetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
    );
    await captureRejection(
      new ChatVectorClient({
        baseUrl: "https://api.chatvector.test",
        fetch,
        retry: { maxRetries: 5 },
      }).batchChat({ queries: [{ question: "Q", docIds: [DOCUMENT_ID] }] }),
    );
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    [null, "queries"],
    [{}, "queries"],
    [{ queries: [{ question: "", docIds: [DOCUMENT_ID] }] }, "question"],
    [{ queries: [{ question: "Q", docIds: null }] }, "docIds"],
  ])("rejects malformed batch input before fetch", async (request, field) => {
    const fetch = createFetchMock(jsonResponse(batchPartialPayload));
    const error = await captureRejection(
      makeClient(fetch).batchChat(request as never),
    );
    expect(error).toBeInstanceOf(TypeError);
    expect((error as Error).message).toContain(field);
    expect(fetch).not.toHaveBeenCalled();
  });
});

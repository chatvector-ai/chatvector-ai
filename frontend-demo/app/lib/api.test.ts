import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { sendMessage, sendBatchMessage, sendSynthesizedBatchMessage, ChatError, getDocumentStatus } from "./api";

const MOCK_RESPONSE = {
  question: "What is RAG?",
  chunks: 3,
  answer: "RAG stands for Retrieval-Augmented Generation.",
  sources: [
    { file_name: "doc.pdf", page_number: 1, chunk_index: 0, score: 0.91 },
  ],
  latency_ms: 2100,
  model: "gemini-2.5-flash",
  doc_id: "doc-123",
};

vi.mock("./session", () => ({ getSessionId: () => "test-session-id" }));

describe("sendMessage", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns parsed response on success", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(MOCK_RESPONSE), { status: 200 })
    );

    const result = await sendMessage("What is RAG?", "doc-123");

    expect(result).toEqual(MOCK_RESPONSE);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat"),
      expect.objectContaining({
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "X-Session-Id": "test-session-id",
        },
        body: JSON.stringify({
          question: "What is RAG?",
          doc_id: "doc-123",
          match_count: 5,
          session_id: "test-session-id",
        }),
      })
    );
  });

  it.each([
    [
      "llm_missing_api_key",
      "No API key is configured. Check your `LLM_API_KEY` environment variable.",
    ],
    [
      "llm_invalid_api_key",
      "The configured API key was rejected. Verify your `LLM_API_KEY` is correct.",
    ],
    [
      "llm_rate_limited",
      "The LLM provider is rate limiting requests. Try again in a moment.",
    ],
    [
      "llm_timeout_or_connection",
      "The LLM provider timed out. Check your network and try again.",
    ],
    [
      "llm_unexpected",
      "An unexpected error occurred with the LLM provider.",
    ],
  ])("returns full response for %s soft failures", async (code) => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          ...MOCK_RESPONSE,
          status: "error",
          error: { code, message: "Backend provider error." },
        }),
        { status: 200 }
      )
    );

    const result = await sendMessage("q", "doc-123");

    expect(result.status).toBe("error");
    expect(result.error).toEqual({ code, message: "Backend provider error." });
    expect(result.answer).toBe(MOCK_RESPONSE.answer);
    expect(result.sources).toEqual(MOCK_RESPONSE.sources);
    expect(result.chunks).toBe(MOCK_RESPONSE.chunks);
    expect(result.latency_ms).toBe(MOCK_RESPONSE.latency_ms);
    expect(result.model).toBe(MOCK_RESPONSE.model);
  });

  it("falls back to the generic LLM message for unknown soft failure codes", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          ...MOCK_RESPONSE,
          status: "error",
          error: { code: "llm_error", message: "Provider failed." },
        }),
        { status: 200 }
      )
    );

    const result = await sendMessage("q", "doc-123");

    expect(result.status).toBe("error");
    expect(result.error).toEqual({ code: "llm_error", message: "Provider failed." });
    expect(result.answer).toBe(MOCK_RESPONSE.answer);
  });

  it("throws no_document on 404", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 404 })
    );

    await expect(sendMessage("q", "bad-id")).rejects.toThrow(ChatError);
    await expect(sendMessage("q", "bad-id")).rejects.toMatchObject({
      code: "no_document",
    });
  });

  it("throws unexpected on 422", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 422 })
    );

    await expect(sendMessage("q", "bad-id")).rejects.toThrow(ChatError);
    await expect(sendMessage("q", "bad-id")).rejects.toMatchObject({
      code: "unexpected",
    });
  });

  it("throws backend_unreachable on network failure", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("fetch failed"));

    await expect(sendMessage("q", "doc-123")).rejects.toThrow(ChatError);
    await expect(sendMessage("q", "doc-123")).rejects.toMatchObject({
      code: "backend_unreachable",
    });
  });

  it("throws unexpected on 500", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 500 })
    );

    await expect(sendMessage("q", "doc-123")).rejects.toThrow(ChatError);
    await expect(sendMessage("q", "doc-123")).rejects.toMatchObject({
      code: "unexpected",
    });
  });
});

describe("sendBatchMessage", () => {
  const originalFetch = globalThis.fetch;

  const BATCH_RESPONSE = {
    count: 2,
    success_count: 1,
    failure_count: 1,
    results: [
      {
        status: "ok",
        question: "Summary?",
        doc_ids: ["doc-1"],
        chunks: 2,
        answer: "First summary.",
        sources: [{ file_name: "a.pdf", page_number: 1, chunk_index: 0, score: 0.77 }],
        latency_ms: 1800,
        model: "gemini-2.5-flash",
        session_id: "sess-1",
      },
      {
        status: "error",
        question: "Summary?",
        doc_ids: ["doc-2"],
        chunks: 1,
        answer: "Partial answer.",
        sources: [{ file_name: "b.pdf", page_number: 3, chunk_index: 2, score: 0.64 }],
        latency_ms: 2200,
        model: "gemini-2.5-flash",
        error: { code: "llm_rate_limited", message: "Slow down." },
      },
    ],
  };

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("sends one query item per document and returns parsed results", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(BATCH_RESPONSE), { status: 200 })
    );

    const result = await sendBatchMessage("Summary?", ["doc-1", "doc-2"]);

    expect(result).toEqual(BATCH_RESPONSE);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat/batch"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          queries: [
            { question: "Summary?", doc_ids: ["doc-1"], match_count: 5 },
            { question: "Summary?", doc_ids: ["doc-2"], match_count: 5 },
          ],
          session_id: "test-session-id",
        }),
      })
    );
  });

  it("throws backend_unreachable on network failure", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("fetch failed"));

    await expect(sendBatchMessage("q", ["doc-1"])).rejects.toMatchObject({
      name: "ChatError",
      code: "backend_unreachable",
    });
  });

  it("throws unexpected on a 500 response", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response(null, { status: 500 }));

    await expect(sendBatchMessage("q", ["doc-1"])).rejects.toMatchObject({
      name: "ChatError",
      code: "unexpected",
    });
  });
});

describe("sendSynthesizedBatchMessage", () => {
  const originalFetch = globalThis.fetch;

  const SYNTHESIZED_RESPONSE = {
    count: 1,
    success_count: 1,
    failure_count: 0,
    results: [
      {
        status: "ok",
        question: "Cross-doc question?",
        doc_ids: ["doc-1", "doc-2", "doc-3"],
        chunks: 5,
        answer: "Combined synthesized answer.",
        sources: [
          { file_name: "a.pdf", page_number: 1, chunk_index: 0, score: 0.88 },
          { file_name: "b.pdf", page_number: 2, chunk_index: 1, score: 0.74 },
        ],
        latency_ms: 2400,
        model: "gemini-2.5-flash",
        session_id: "sess-1",
      },
    ],
  };

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("sends one query item with all doc_ids and returns parsed results", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(SYNTHESIZED_RESPONSE), { status: 200 })
    );

    const result = await sendSynthesizedBatchMessage("Cross-doc question?", [
      "doc-1",
      "doc-2",
      "doc-3",
    ]);

    expect(result).toEqual(SYNTHESIZED_RESPONSE);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat/batch"),
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Session-Id": "test-session-id",
        },
        body: JSON.stringify({
          queries: [
            {
              question: "Cross-doc question?",
              doc_ids: ["doc-1", "doc-2", "doc-3"],
              match_count: 5,
            },
          ],
          session_id: "test-session-id",
        }),
      })
    );
  });
});

describe("getDocumentStatus", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns numeric chunk progress from polling responses", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "embedding",
          stage: "embedding",
          chunks: { processed: 0, total: 24 },
        }),
        { status: 200 }
      )
    );

    await expect(getDocumentStatus("/documents/doc-123/status")).resolves.toEqual({
      status: "embedding",
      stage: "embedding",
      chunks: { processed: 0, total: 24 },
    });
  });

  it("drops malformed chunk progress instead of passing it to the UI", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "embedding",
          stage: "embedding",
          chunks: { processed: "0", total: "24" },
        }),
        { status: 200 }
      )
    );

    await expect(getDocumentStatus("/documents/doc-123/status")).resolves.toEqual({
      status: "embedding",
      stage: "embedding",
    });
  });

  it("parses queue_position from queued status responses", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "queued",
          stage: "queued",
          queue_position: 3,
        }),
        { status: 200 }
      )
    );

    await expect(getDocumentStatus("/documents/doc-123/status")).resolves.toEqual({
      status: "queued",
      stage: "queued",
      queue_position: 3,
    });
  });

  it("drops queue_position when absent so non-queued responses stay clean", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "embedding",
          stage: "embedding",
        }),
        { status: 200 }
      )
    );

    await expect(getDocumentStatus("/documents/doc-123/status")).resolves.toEqual({
      status: "embedding",
      stage: "embedding",
    });
  });

  it("drops malformed queue_position values", async () => {
    for (const bad of [0, -1, 1.5, "3", null, true]) {
      vi.mocked(globalThis.fetch).mockResolvedValue(
        new Response(
          JSON.stringify({
            status: "queued",
            stage: "queued",
            queue_position: bad,
          }),
          { status: 200 }
        )
      );

      const result = await getDocumentStatus("/documents/doc-123/status");
      expect(result.queue_position).toBeUndefined();
    }
  });

  it("surfaces a queue_position that drops from 3 to 1 across polls", async () => {
    // First poll: upload returned position 3, still queued.
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "queued",
          stage: "queued",
          queue_position: 3,
        }),
        { status: 200 }
      )
    );
    await expect(getDocumentStatus("/documents/doc-123/status")).resolves.toEqual({
      status: "queued",
      stage: "queued",
      queue_position: 3,
    });

    // Second poll: queue has advanced, position is now 1.
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "queued",
          stage: "queued",
          queue_position: 1,
        }),
        { status: 200 }
      )
    );
    await expect(getDocumentStatus("/documents/doc-123/status")).resolves.toEqual({
      status: "queued",
      stage: "queued",
      queue_position: 1,
    });
  });
});

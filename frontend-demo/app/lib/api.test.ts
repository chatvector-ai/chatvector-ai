import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  sendMessage,
  sendMessageStream,
  sendBatchMessage,
  sendSynthesizedBatchMessage,
  ChatError,
  StreamingDisabledError,
  getDocumentStatus,
  uploadDocument,
  deleteDocument,
} from "./api";
import { BackendApiError } from "./apiErrors";

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
          scope: "session",
          session_id: "test-session-id",
        }),
      })
    );
  });

  it("passes custom scope and match_count when provided", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(MOCK_RESPONSE), { status: 200 })
    );

    await sendMessage("What is RAG?", "doc-123", {
      matchCount: 12,
      scope: "tenant",
    });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat"),
      expect.objectContaining({
        body: JSON.stringify({
          question: "What is RAG?",
          doc_id: "doc-123",
          match_count: 12,
          scope: "tenant",
          session_id: "test-session-id",
        }),
      })
    );
  });

  it("clamps out-of-range match_count before sending", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(MOCK_RESPONSE), { status: 200 })
    );

    await sendMessage("q", "doc-123", { matchCount: 99 });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        body: JSON.stringify({
          question: "q",
          doc_id: "doc-123",
          match_count: 20,
          scope: "session",
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

  it("throws no_document on 404 with structured backend detail", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "document_not_found",
            message: "Document not found.",
          },
        }),
        { status: 404 }
      )
    );

    await expect(sendMessage("q", "bad-id")).rejects.toMatchObject({
      code: "no_document",
      message: "Document not found.",
      backendCode: "document_not_found",
    });
  });

  it("throws no_document with a friendly fallback on bodyless 404", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 404 })
    );

    await expect(sendMessage("q", "bad-id")).rejects.toMatchObject({
      code: "no_document",
      message: "Document not found. It may have been deleted.",
    });
  });

  it("throws api_error with validation field hints on 422", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "validation_error",
            message: "Request validation failed",
            fields: [
              {
                loc: ["body", "question"],
                msg: "ensure this value has at most 2000 characters",
              },
            ],
          },
        }),
        { status: 422 }
      )
    );

    await expect(sendMessage("q", "bad-id")).rejects.toMatchObject({
      code: "api_error",
      backendCode: "validation_error",
      message:
        "Request validation failed\nquestion: ensure this value has at most 2000 characters",
      fields: [
        {
          loc: ["body", "question"],
          msg: "ensure this value has at most 2000 characters",
        },
      ],
    });
  });

  it("throws backend_unreachable on network failure", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("fetch failed"));

    await expect(sendMessage("q", "doc-123")).rejects.toThrow(ChatError);
    await expect(sendMessage("q", "doc-123")).rejects.toMatchObject({
      code: "backend_unreachable",
    });
  });

  it("throws api_error with a fallback message on 500", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 500 })
    );

    await expect(sendMessage("q", "doc-123")).rejects.toMatchObject({
      code: "api_error",
      message: "Server error (500). Please try again.",
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
          scope: "session",
          queries: [
            { question: "Summary?", doc_ids: ["doc-1"], match_count: 5 },
            { question: "Summary?", doc_ids: ["doc-2"], match_count: 5 },
          ],
          session_id: "test-session-id",
        }),
      })
    );
  });

  it("sends batch-level scope when provided", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(BATCH_RESPONSE), { status: 200 })
    );

    await sendBatchMessage("Summary?", ["doc-1"], {
      matchCount: 8,
      scope: "tenant",
    });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat/batch"),
      expect.objectContaining({
        body: JSON.stringify({
          scope: "tenant",
          queries: [
            { question: "Summary?", doc_ids: ["doc-1"], match_count: 8 },
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

  it("throws rate_limited with the backend message on 429", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "rate_limited",
            message: "Too many requests. Please slow down.",
          },
        }),
        { status: 429 }
      )
    );

    await expect(sendBatchMessage("q", ["doc-1"])).rejects.toMatchObject({
      name: "ChatError",
      code: "rate_limited",
      message: "Too many requests. Please slow down.",
      backendCode: "rate_limited",
    });
  });

  it("throws rate_limited with a friendly fallback on bodyless 429", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 429 })
    );

    await expect(sendBatchMessage("q", ["doc-1"])).rejects.toMatchObject({
      code: "rate_limited",
      message: "Too many requests — please wait a moment and try again.",
    });
  });

  it("throws api_error with a fallback message on a 500 response", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(new Response(null, { status: 500 }));

    await expect(sendBatchMessage("q", ["doc-1"])).rejects.toMatchObject({
      name: "ChatError",
      code: "api_error",
      message: "Server error (500). Please try again.",
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
          scope: "session",
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

describe("uploadDocument", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("throws BackendApiError with structured backend detail", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "unsupported_file_type",
            message: "Only PDF, TXT, and DOCX files are supported.",
          },
        }),
        { status: 422 }
      )
    );

    const file = new File(["content"], "test.exe", {
      type: "application/octet-stream",
    });

    await expect(uploadDocument(file)).rejects.toMatchObject({
      name: "BackendApiError",
      message: "Only PDF, TXT, and DOCX files are supported.",
      httpStatus: 422,
      parsed: {
        code: "unsupported_file_type",
        message: "Only PDF, TXT, and DOCX files are supported.",
      },
    });
    await expect(uploadDocument(file)).rejects.toBeInstanceOf(BackendApiError);
  });

  it("throws rate_limited with a friendly fallback on bodyless 429", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 429 })
    );

    const file = new File(["content"], "test.pdf", { type: "application/pdf" });

    await expect(uploadDocument(file)).rejects.toMatchObject({
      name: "BackendApiError",
      message: "Too many requests — please wait a moment and try again.",
      httpStatus: 429,
    });
  });
});

describe("deleteDocument", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns gone for 204 and 404 responses", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(null, { status: 204 })
    );
    await expect(deleteDocument("doc-1")).resolves.toEqual({ status: "gone" });

    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(null, { status: 404 })
    );
    await expect(deleteDocument("doc-1")).resolves.toEqual({ status: "gone" });
  });

  it("returns conflict with structured backend detail on 409", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: {
            code: "document_in_use",
            message: "Document cannot be deleted while in 'processing' state.",
          },
        }),
        { status: 409 }
      )
    );

    await expect(deleteDocument("doc-1")).resolves.toEqual({
      status: "conflict",
      message: "Document cannot be deleted while in 'processing' state.",
    });
  });

  it("returns error with a fallback message on unexpected failures", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 500 })
    );

    await expect(deleteDocument("doc-1")).resolves.toEqual({
      status: "error",
      message: "Could not remove the document. Try again.",
    });
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

  it("throws DocumentNotFoundError with a friendly fallback on bodyless 404", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 404 })
    );

    await expect(getDocumentStatus("/documents/doc-123/status")).rejects.toMatchObject({
      name: "DocumentNotFoundError",
      message: "Document not found.",
    });
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

// ---------------------------------------------------------------------------
// sendMessageStream
// ---------------------------------------------------------------------------

/** Create a ReadableStream that emits raw SSE text. */
function createSSEStream(events: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(events));
      controller.close();
    },
  });
}

describe("sendMessageStream", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("yields token, complete, and done events from a successful stream", async () => {
    const sseBody = [
      'event: token\ndata: "Hello"\n\n',
      'event: token\ndata: " world"\n\n',
      'event: complete\ndata: {"type":"complete","sources":[],"latency_ms":200,"model":"m"}\n\n',
      'event: done\ndata: [DONE]\n\n',
    ].join("");

    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(createSSEStream(sseBody), {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      })
    );

    const events = [];
    for await (const event of sendMessageStream("q", "doc-123")) {
      events.push(event);
    }

    expect(events).toEqual([
      { type: "token", text: "Hello" },
      { type: "token", text: " world" },
      { type: "complete", sources: [], latency_ms: 200, model: "m" },
      { type: "done" },
    ]);
  });

  it("sends correct headers and body", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(createSSEStream("event: done\ndata: [DONE]\n\n"), {
        status: 200,
      })
    );

    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    for await (const _ of sendMessageStream("What is RAG?", "doc-123")) {
      // consume
    }

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/chat/stream"),
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
          scope: "session",
          session_id: "test-session-id",
        }),
      })
    );
  });

  it("throws StreamingDisabledError on 400 with streaming_disabled", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "streaming_disabled", message: "Streaming disabled." },
        }),
        { status: 400 }
      )
    );

    const gen = sendMessageStream("q", "doc-123");
    await expect(gen.next()).rejects.toThrow(StreamingDisabledError);
  });

  it("throws ChatError no_document on 404", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 404 })
    );

    const gen = sendMessageStream("q", "bad-id");
    await expect(gen.next()).rejects.toThrow(ChatError);
    const gen2 = sendMessageStream("q", "bad-id");
    await expect(gen2.next()).rejects.toMatchObject({ code: "no_document" });
  });

  it("throws ChatError backend_unreachable on network failure", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("fetch failed"));

    const gen = sendMessageStream("q", "doc-123");
    await expect(gen.next()).rejects.toThrow(ChatError);
    const gen2 = sendMessageStream("q", "doc-123");
    await expect(gen2.next()).rejects.toMatchObject({ code: "backend_unreachable" });
  });

  it("throws ChatError unexpected on 500", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(null, { status: 500 })
    );

    const gen = sendMessageStream("q", "doc-123");
    await expect(gen.next()).rejects.toThrow(ChatError);
  });
});

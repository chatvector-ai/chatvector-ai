import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { sendMessage, ChatError } from "./api";

const MOCK_RESPONSE = {
  question: "What is RAG?",
  chunks: 3,
  answer: "RAG stands for Retrieval-Augmented Generation.",
  sources: [
    { file_name: "doc.pdf", page_number: 1, chunk_index: 0 },
  ],
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
  ])("throws a helpful message for %s soft failures", async (code, message) => {
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

    await expect(sendMessage("q", "doc-123")).rejects.toMatchObject({
      name: "ChatError",
      code,
      message,
    });
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

    await expect(sendMessage("q", "doc-123")).rejects.toMatchObject({
      name: "ChatError",
      code: "llm_unexpected",
      message: "An unexpected error occurred with the LLM provider.",
    });
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

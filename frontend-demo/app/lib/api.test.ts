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
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: "What is RAG?",
          doc_id: "doc-123",
          match_count: 5,
        }),
      })
    );
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

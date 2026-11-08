import { describe, it, expect, vi } from "vitest";
import { buildChatRequestBody } from "./buildChatBody";

vi.mock("./session", () => ({ getSessionId: () => "test-session-id" }));

describe("buildChatRequestBody", () => {
  it("omits retrieval overrides when nothing was set explicitly", () => {
    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      retrieval: { explicit: {} },
    });

    expect(body).toEqual({
      question: "q",
      doc_id: "doc-1",
      session_id: "test-session-id",
    });
    expect(body).not.toHaveProperty("match_count");
    expect(body).not.toHaveProperty("scope");
    expect(body).not.toHaveProperty("hybrid_enabled");
    expect(body).not.toHaveProperty("history");
    expect(body).not.toHaveProperty("metadata_filter");
  });

  it("includes only fields the user explicitly set", () => {
    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      retrieval: {
        explicit: {
          hybridEnabled: true,
          retrievalHistoryWindow: 6,
        },
      },
    });

    expect(body.hybrid_enabled).toBe(true);
    expect(body).not.toHaveProperty("reranking_enabled");
    expect(body.history).toEqual({ retrieval_history_window: 6 });
  });

  it("sends scope and match_count when explicitly set", () => {
    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      retrieval: {
        explicit: { scope: "tenant", matchCount: 9 },
      },
    });

    expect(body.scope).toBe("tenant");
    expect(body.match_count).toBe(9);
  });

  it("sends metadata_filter when explicitly set", () => {
    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      retrieval: {
        explicit: { metadataFilter: { department: "legal" } },
      },
    });

    expect(body.metadata_filter).toEqual({ department: "legal" });
  });

  it("sends preset on the nested retrieval object only", () => {
    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      retrieval: { explicit: { preset: "alpha" } },
    });

    expect(body.retrieval).toEqual({ preset: "alpha" });
    expect(body).not.toHaveProperty("match_count");
    expect(body).not.toHaveProperty("scope");
    expect(body).not.toHaveProperty("hybrid_enabled");
  });

  it("sends hybrid_enabled alongside a nested preset when explicitly set", () => {
    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      retrieval: {
        explicit: { preset: "alpha", hybridEnabled: true },
      },
    });

    expect(body.retrieval).toEqual({ preset: "alpha" });
    expect(body.hybrid_enabled).toBe(true);
  });

  it("omits preset after it is cleared", () => {
    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      retrieval: { explicit: { matchCount: 7 } },
    });

    expect(body).not.toHaveProperty("retrieval");
    expect(body.match_count).toBe(7);
  });

  it("adds debug_retrieval without implicit retrieval fields", () => {
    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      debugRetrieval: true,
      retrieval: { explicit: {} },
    });

    expect(body.debug_retrieval).toBe(true);
    expect(body).not.toHaveProperty("match_count");
  });
});

import { describe, it, expect } from "vitest";
import {
  deduplicatedSources,
  formatCitationLine,
  formatCitationSummary,
  formatLatencySeconds,
  formatResponseMetadata,
  formatSourceCitation,
  hasInspectableRetrievalData,
  inspectorEffectiveConfigFields,
  inspectorRerankerFields,
  inspectorSourceFields,
  inspectorTimingStageFields,
  rankingScoreFieldLabel,
} from "./citations";
import type { ChatSource } from "./api";

describe("citations helpers", () => {
  it("deduplicates sources that share a start page but differ at page_end", () => {
    const sources: ChatSource[] = [
      { file_name: "a.pdf", page_number: 3, page_end: 4, chunk_index: 0 },
      { file_name: "a.pdf", page_number: 3, page_end: 5, chunk_index: 0 },
    ];

    expect(deduplicatedSources(sources)).toEqual(sources);
  });

  it("deduplicates by file, page, and chunk index", () => {
    const sources: ChatSource[] = [
      { file_name: "a.pdf", page_number: 2, chunk_index: 0 },
      { file_name: "a.pdf", page_number: 2, chunk_index: 1 },
      { file_name: "a.pdf", page_number: 2, chunk_index: 0 },
    ];

    expect(deduplicatedSources(sources)).toEqual([
      { file_name: "a.pdf", page_number: 2, chunk_index: 0 },
      { file_name: "a.pdf", page_number: 2, chunk_index: 1 },
    ]);
  });

  it("formats citation lines with page, chunk, and score", () => {
    expect(
      formatCitationLine({
        file_name: "report.pdf",
        page_number: 2,
        chunk_index: 3,
        score: 0.82,
      })
    ).toBe("report.pdf · p.2 · chunk 3 · score 0.82");
  });

  it("omits score when null", () => {
    expect(
      formatCitationLine({
        file_name: "report.pdf",
        page_number: 2,
        chunk_index: 3,
        score: null,
      })
    ).toBe("report.pdf · p.2 · chunk 3");
  });

  it("formats response metadata footer", () => {
    expect(
      formatResponseMetadata({
        chunks: 3,
        model: "gemini-2.5-flash",
        latency_ms: 2100,
      })
    ).toBe("3 chunks · gemini-2.5-flash · 2.1s");
  });

  it("formats sub-second latency in milliseconds", () => {
    expect(formatLatencySeconds(450)).toBe("450ms");
  });

  it("detects when retrieval inspector data is available", () => {
    expect(hasInspectableRetrievalData({})).toBe(false);
    expect(hasInspectableRetrievalData({ question: "What is RAG?" })).toBe(true);
    expect(
      hasInspectableRetrievalData({
        sources: [{ file_name: "a.pdf", page_number: 1, chunk_index: 0 }],
      })
    ).toBe(true);
    expect(hasInspectableRetrievalData({ chunks: 0 })).toBe(true);
    expect(
      hasInspectableRetrievalData({
        retrieval_debug: {
          transformed_queries: ["expanded query"],
        },
      })
    ).toBe(true);
    expect(
      hasInspectableRetrievalData({
        retrieval_debug: {
          history_resolution_skipped_reason: "standalone_question",
        },
      })
    ).toBe(true);
    expect(
      hasInspectableRetrievalData({
        retrieval_debug: {
          effective_retrieval_query: "resolved follow-up",
        },
      })
    ).toBe(true);
  });

  it("labels vector and hybrid RRF ranking scores on different scales", () => {
    expect(rankingScoreFieldLabel("vector")).toBe("Vector similarity score");
    expect(rankingScoreFieldLabel("hybrid_rrf")).toBe("Hybrid RRF score");
    expect(rankingScoreFieldLabel("vector")).not.toMatch(/confidence/i);
    expect(rankingScoreFieldLabel("hybrid_rrf")).not.toMatch(/confidence/i);

    expect(
      inspectorSourceFields({
        file_name: "a.pdf",
        page_number: 1,
        chunk_index: 0,
        score: 0.82,
        score_type: "vector",
      })
    ).toEqual(
      expect.arrayContaining([
        { label: "Vector similarity score", value: "0.82" },
      ])
    );

    expect(
      inspectorSourceFields({
        file_name: "b.pdf",
        page_number: 1,
        chunk_index: 0,
        score: 0.016,
        score_type: "hybrid_rrf",
      })
    ).toEqual(
      expect.arrayContaining([
        { label: "Hybrid RRF score", value: "0.02" },
      ])
    );
  });

  it("omits score type from inspector fields when absent", () => {
    expect(
      inspectorSourceFields({
        file_name: "report.pdf",
        page_number: null,
        chunk_index: 0,
        score: null,
      })
    ).toEqual([
      { label: "File", value: "report.pdf" },
      { label: "Chunk", value: "0" },
    ]);
  });

  it("formats inspector component score fields when present", () => {
    expect(
      inspectorSourceFields({
        file_name: "report.pdf",
        page_number: 2,
        chunk_index: 3,
        score: 0.77,
        score_type: "reranked",
        vector_score: 0.55,
        full_text_score: 0.42,
        rrf_score: 0.03,
        reranker_score: 0.77,
        rerank_order: 1,
      })
    ).toEqual([
      { label: "File", value: "report.pdf" },
      { label: "Page", value: "2" },
      { label: "Chunk", value: "3" },
      { label: "Reranked score", value: "0.77" },
      { label: "Vector similarity", value: "0.55" },
      { label: "Full-text score", value: "0.42" },
      { label: "RRF score", value: "0.03" },
      { label: "Reranker score", value: "0.77" },
      { label: "Rerank order", value: "1" },
    ]);
  });

  it("omits component score fields when absent", () => {
    expect(
      inspectorSourceFields({
        file_name: "report.pdf",
        page_number: 1,
        chunk_index: 0,
        score: 0.82,
        score_type: "vector",
      })
    ).toEqual([
      { label: "File", value: "report.pdf" },
      { label: "Page", value: "1" },
      { label: "Chunk", value: "0" },
      { label: "Vector similarity score", value: "0.82" },
    ]);
  });

  it("formats effective config entries with field source", () => {
    expect(
      inspectorEffectiveConfigFields({
        hybrid_enabled: { value: true, source: "request" },
        match_count: { value: 5, source: "env" },
      })
    ).toEqual([
      { label: "Hybrid Enabled", value: "true (request)" },
      { label: "Match Count", value: "5 (env)" },
    ]);
  });

  it("formats reranker fallback and omits rerank when absent", () => {
    expect(
      inspectorRerankerFields({
        provider: "cohere",
        fallback_reason: "timeout",
      })
    ).toEqual([
      { label: "Provider", value: "cohere" },
      { label: "Fallback reason", value: "timeout" },
    ]);
    expect(inspectorRerankerFields({})).toEqual([]);
  });

  it("formats timing stages when present", () => {
    expect(
      inspectorTimingStageFields({
        search: 120,
        total: 450,
      })
    ).toEqual([
      { label: "Search", value: "120ms" },
      { label: "Retrieval total", value: "450ms" },
    ]);
  });

  it("detects inspectable debug payloads for config rerank and timings", () => {
    expect(
      hasInspectableRetrievalData({
        retrieval_debug: {
          effective_config: {
            hybrid_enabled: { value: false, source: "env" },
          },
        },
      })
    ).toBe(true);
    expect(
      hasInspectableRetrievalData({
        retrieval_debug: { reranker: { provider: "similarity" } },
      })
    ).toBe(true);
    expect(
      hasInspectableRetrievalData({
        retrieval_debug: { timing_ms: { search: 10 } },
        request_latency_ms: 900,
      })
    ).toBe(true);
  });

  it("keeps citation lines unchanged when component scores are present", () => {
    expect(
      formatCitationLine({
        file_name: "report.pdf",
        page_number: 2,
        chunk_index: 3,
        score: 0.77,
        score_type: "reranked",
        vector_score: 0.55,
        reranker_score: 0.77,
        rerank_order: 1,
      })
    ).toBe("report.pdf · p.2 · chunk 3 · score 0.77");
  });

  it("formats inclusive page span on the visible citation line", () => {
    expect(
      formatSourceCitation({
        file_name: "report.pdf",
        page_number: 1,
        page_end: 2,
        chunk_index: 0,
      }),
    ).toBe("report.pdf · p.1-2 · chunk 0");

    expect(
      formatSourceCitation({
        file_name: "report.pdf",
        page_number: 7,
        page_end: null,
        chunk_index: 1,
      }),
    ).toBe("report.pdf · p.7 · chunk 1");
  });

  it("formats visible source citation with file and location without score", () => {
    expect(
      formatSourceCitation({
        file_name: "notes.txt",
        chunk_index: 0,
        score: 0.63,
        score_type: "vector",
      })
    ).toBe("notes.txt · chunk 0");

    expect(
      formatSourceCitation({
        file_name: "report.pdf",
        page_number: 4,
        chunk_index: 2,
        score: 0.88,
      })
    ).toBe("report.pdf · p.4 · chunk 2");

    expect(
      formatSourceCitation({
        file_name: "report.pdf",
        page_number: 1,
        page_end: 2,
        chunk_index: 0,
        score: 0.77,
      }),
    ).toBe("report.pdf · p.1-2 · chunk 0");
  });

  it("formats deduplicated citation summary and returns null when empty", () => {
    expect(formatCitationSummary(undefined)).toBeNull();
    expect(formatCitationSummary([])).toBeNull();
    expect(
      formatCitationSummary([
        { file_name: "notes.txt", chunk_index: 0, score: 0.63 },
        { file_name: "notes.txt", chunk_index: 0, score: 0.63 },
        { file_name: "report.pdf", page_number: 2, chunk_index: 1, score: 0.91 },
      ])
    ).toBe("notes.txt · chunk 0 · report.pdf · p.2 · chunk 1");
  });
});

import { describe, it, expect } from "vitest";
import {
  deduplicatedSources,
  formatCitationLine,
  formatLatencySeconds,
  formatResponseMetadata,
  hasInspectableRetrievalData,
  inspectorSourceFields,
} from "./citations";
import type { ChatSource } from "./api";

describe("citations helpers", () => {
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
  });

  it("formats inspector source fields with score type when present", () => {
    expect(
      inspectorSourceFields({
        file_name: "report.pdf",
        page_number: 2,
        chunk_index: 3,
        score: 0.82,
        score_type: "vector",
      })
    ).toEqual([
      { label: "File", value: "report.pdf" },
      { label: "Page", value: "2" },
      { label: "Chunk", value: "3" },
      { label: "Score", value: "0.82" },
      { label: "Score type", value: "vector" },
    ]);
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
});

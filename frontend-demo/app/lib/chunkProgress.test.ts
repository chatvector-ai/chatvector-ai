import { describe, expect, it } from "vitest";
import { formatChunkProgress, shouldShowChunkProgress } from "./chunkProgress";

describe("formatChunkProgress", () => {
  it("shows processed and total chunk progress", () => {
    expect(formatChunkProgress({ processed: 7, total: 24 })).toBe(
      "7 / 24 chunks"
    );
  });

  it("shows zero processed chunks during early embedding progress", () => {
    expect(formatChunkProgress({ processed: 0, total: 24 })).toBe(
      "0 / 24 chunks"
    );
  });

  it("uses the singular chunk label for one total chunk", () => {
    expect(formatChunkProgress({ processed: 1, total: 1 })).toBe(
      "1 / 1 chunk"
    );
  });
});

describe("shouldShowChunkProgress", () => {
  it("shows progress only while the embedding stage is active", () => {
    expect(
      shouldShowChunkProgress({
        stageKey: "embedding",
        state: "active",
        chunks: { processed: 0, total: 24 },
      })
    ).toBe(true);
  });

  it("hides progress outside the embedding stage", () => {
    expect(
      shouldShowChunkProgress({
        stageKey: "chunking",
        state: "active",
        chunks: { processed: 7, total: 24 },
      })
    ).toBe(false);
  });

  it("hides stale progress after embedding is no longer active", () => {
    expect(
      shouldShowChunkProgress({
        stageKey: "embedding",
        state: "completed",
        chunks: { processed: 24, total: 24 },
      })
    ).toBe(false);
  });

  it("hides progress when chunk data is missing", () => {
    expect(
      shouldShowChunkProgress({
        stageKey: "embedding",
        state: "active",
      })
    ).toBe(false);
  });

  it("hides progress for an empty total without rendering a stray zero", () => {
    expect(
      shouldShowChunkProgress({
        stageKey: "embedding",
        state: "active",
        chunks: { processed: 0, total: 0 },
      })
    ).toBe(false);
  });
});

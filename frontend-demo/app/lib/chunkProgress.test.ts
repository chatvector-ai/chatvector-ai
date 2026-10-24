import { describe, expect, it } from "vitest";
import {
  formatChunkProgress,
  resolveStageForChunkAnimation,
  shouldShowChunkProgress,
} from "./chunkProgress";
import { PIPELINE_STAGES } from "./stageLabels";

describe("formatChunkProgress", () => {
  it("shows processed and total chunk progress", () => {
    expect(formatChunkProgress({ processed: 7, total: 24 })).toBe("7 / 24");
  });

  it("shows zero processed chunks during early embedding progress", () => {
    expect(formatChunkProgress({ processed: 0, total: 24 })).toBe("0 / 24");
  });

  it("shows progress when only one chunk exists", () => {
    expect(formatChunkProgress({ processed: 1, total: 1 })).toBe("1 / 1");
  });
});

describe("resolveStageForChunkAnimation", () => {
  it("holds on embedding while the animated count is still catching up", () => {
    expect(
      resolveStageForChunkAnimation({
        currentStage: "storing",
        animatedProcessed: 120,
        chunkTarget: 137,
        failed: false,
        pipelineStages: PIPELINE_STAGES,
      })
    ).toBe("embedding");
  });

  it("releases once the animated count reaches the target", () => {
    expect(
      resolveStageForChunkAnimation({
        currentStage: "storing",
        animatedProcessed: 137,
        chunkTarget: 137,
        failed: false,
        pipelineStages: PIPELINE_STAGES,
      })
    ).toBe("storing");
  });

  it("surfaces retrying immediately without holding on embedding", () => {
    expect(
      resolveStageForChunkAnimation({
        currentStage: "retrying",
        animatedProcessed: 120,
        chunkTarget: 137,
        failed: false,
        pipelineStages: PIPELINE_STAGES,
      })
    ).toBe("retrying");
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

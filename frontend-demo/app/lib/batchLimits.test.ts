import { describe, expect, it } from "vitest";
import {
  BATCH_MAX_COMPARE_ITEMS,
  BATCH_MAX_SYNTHESIZE_DOC_IDS,
  batchSelectionLimit,
  batchSelectionWithinLimit,
  canAddBatchSelection,
} from "./batchLimits";

describe("batchLimits", () => {
  it("uses backend default caps for compare and synthesize modes", () => {
    expect(batchSelectionLimit("compare")).toBe(BATCH_MAX_COMPARE_ITEMS);
    expect(batchSelectionLimit("synthesize")).toBe(BATCH_MAX_SYNTHESIZE_DOC_IDS);
  });

  it("blocks compare selections beyond 20 documents", () => {
    expect(canAddBatchSelection("compare", 20)).toBe(false);
    expect(batchSelectionWithinLimit("compare", 20)).toBe(true);
    expect(batchSelectionWithinLimit("compare", 21)).toBe(false);
  });

  it("blocks synthesize selections beyond 10 documents", () => {
    expect(canAddBatchSelection("synthesize", 10)).toBe(false);
    expect(batchSelectionWithinLimit("synthesize", 10)).toBe(true);
    expect(batchSelectionWithinLimit("synthesize", 11)).toBe(false);
  });

  it("uses the synthesize cap for configuration compare", () => {
    expect(batchSelectionLimit("config-compare")).toBe(BATCH_MAX_SYNTHESIZE_DOC_IDS);
    expect(batchSelectionWithinLimit("config-compare", 10)).toBe(true);
    expect(batchSelectionWithinLimit("config-compare", 11)).toBe(false);
  });
});

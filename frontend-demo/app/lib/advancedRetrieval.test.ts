import { describe, it, expect, beforeEach } from "vitest";
import {
  loadAdvancedRetrievalState,
  saveAdvancedRetrievalState,
  resetAdvancedRetrievalState,
  effectiveScope,
  EMPTY_ADVANCED_RETRIEVAL,
  resolveScopeIndicator,
  selectedPresetName,
  countExplicitOverrides,
} from "./advancedRetrieval";

const STORAGE_KEY = "chatvector-advanced-retrieval-explicit";

describe("advancedRetrieval storage", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("does not persist legacy always-on defaults as explicit overrides", () => {
    sessionStorage.setItem(
      "chatvector-retrieval-settings",
      JSON.stringify({ scope: "session", matchCount: 5 })
    );

    const state = loadAdvancedRetrievalState();
    expect(state.explicit).toEqual({});
    expect(sessionStorage.getItem("chatvector-retrieval-settings")).toBeNull();
  });

  it("loads and saves explicit fields only", () => {
    saveAdvancedRetrievalState({
      explicit: { scope: "tenant", hybridEnabled: true },
    });

    expect(loadAdvancedRetrievalState()).toEqual({
      explicit: { scope: "tenant", hybridEnabled: true },
    });
  });

  it("effectiveScope uses process default when unset", () => {
    expect(effectiveScope(EMPTY_ADVANCED_RETRIEVAL)).toBe("session");
    expect(
      effectiveScope({ explicit: { scope: "tenant" } })
    ).toBe("tenant");
  });

  it("persists an explicitly chosen preset", () => {
    saveAdvancedRetrievalState({ explicit: { preset: "alpha" } });
    expect(loadAdvancedRetrievalState().explicit.preset).toBe("alpha");
    expect(selectedPresetName(loadAdvancedRetrievalState())).toBe("alpha");
  });

  it("resolveScopeIndicator avoids session/tenant when only a preset is set", () => {
    expect(
      resolveScopeIndicator({ explicit: { preset: "alpha" } }, "notes.txt")
    ).toEqual({ kind: "preset" });
  });

  it("resetAdvancedRetrievalState clears explicit fields and sessionStorage", () => {
    saveAdvancedRetrievalState({
      explicit: { scope: "tenant", hybridEnabled: true, matchCount: 12 },
    });
    expect(sessionStorage.getItem(STORAGE_KEY)).not.toBeNull();

    expect(resetAdvancedRetrievalState()).toEqual(EMPTY_ADVANCED_RETRIEVAL);
    expect(loadAdvancedRetrievalState()).toEqual(EMPTY_ADVANCED_RETRIEVAL);
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe("countExplicitOverrides", () => {
  it("returns 0 for empty explicit fields", () => {
    expect(countExplicitOverrides(EMPTY_ADVANCED_RETRIEVAL)).toBe(0);
  });

  it("counts each set field individually", () => {
    expect(
      countExplicitOverrides({ explicit: { scope: "tenant" } })
    ).toBe(1);
    expect(
      countExplicitOverrides({ explicit: { hybridEnabled: true, rerankingEnabled: false } })
    ).toBe(2);
    expect(
      countExplicitOverrides({
        explicit: {
          scope: "tenant",
          matchCount: 10,
          hybridEnabled: true,
          rerankingEnabled: false,
          rerankerProvider: "cohere",
          queryTransformationEnabled: true,
          queryTransformationStrategy: "rewrite",
          historyAwareRetrieval: false,
          retrievalHistoryWindow: 3,
          generationHistoryWindow: 5,
          metadataFilter: { type: "invoice" },
          preset: "alpha",
        },
      })
    ).toBe(12);
  });

  it("does not count historyAwareRetrieval when it is undefined (Default)", () => {
    expect(
      countExplicitOverrides({ explicit: { hybridEnabled: true } })
    ).toBe(1);
  });

  it("counts historyAwareRetrieval when explicitly set to true or false", () => {
    expect(
      countExplicitOverrides({ explicit: { historyAwareRetrieval: true } })
    ).toBe(1);
    expect(
      countExplicitOverrides({ explicit: { historyAwareRetrieval: false } })
    ).toBe(1);
  });

  it("does not count an empty metadataFilter object", () => {
    expect(
      countExplicitOverrides({ explicit: { metadataFilter: {} } })
    ).toBe(0);
  });
});

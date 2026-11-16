import { describe, it, expect, beforeEach } from "vitest";
import {
  loadAdvancedRetrievalState,
  saveAdvancedRetrievalState,
  resetAdvancedRetrievalState,
  effectiveScope,
  effectiveMatchCount,
  fieldInheritSource,
  inheritSourceLabel,
  EMPTY_ADVANCED_RETRIEVAL,
  resolveScopeIndicator,
  selectedPresetName,
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

  it("effectiveScope uses supplied discovery defaults when explicit is unset", () => {
    expect(
      effectiveScope(EMPTY_ADVANCED_RETRIEVAL, { scope: "tenant" })
    ).toBe("tenant");
    expect(
      effectiveScope({ explicit: { scope: "session" } }, { scope: "tenant" })
    ).toBe("session");
  });

  it("effectiveMatchCount uses supplied discovery defaults when explicit is unset", () => {
    expect(
      effectiveMatchCount(EMPTY_ADVANCED_RETRIEVAL, { match_count: 12 })
    ).toBe(12);
    expect(
      effectiveMatchCount({ explicit: { matchCount: 3 } }, { match_count: 12 })
    ).toBe(3);
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

  it("adopts inspector source vocabulary via inheritSourceLabel", () => {
    expect(inheritSourceLabel("explicit")).toBe("Explicit request");
    expect(inheritSourceLabel("preset")).toBe("Preset");
    expect(inheritSourceLabel("default-from-env")).toBe("Default from env");
    expect(inheritSourceLabel("env")).toBe("Default from env");
    expect(inheritSourceLabel("process-default")).toBe("Default from env");
  });

  it("fieldInheritSource resolves explicit, preset, or default-from-env", () => {
    expect(fieldInheritSource({ explicit: { hybridEnabled: true } }, true)).toBe("explicit");
    expect(fieldInheritSource({ explicit: { preset: "alpha" } }, false)).toBe("preset");
    expect(fieldInheritSource(EMPTY_ADVANCED_RETRIEVAL, false)).toBe("default-from-env");
  });
});

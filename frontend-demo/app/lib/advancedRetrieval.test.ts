import { describe, it, expect, beforeEach } from "vitest";
import {
  loadAdvancedRetrievalState,
  saveAdvancedRetrievalState,
  effectiveScope,
  EMPTY_ADVANCED_RETRIEVAL,
} from "./advancedRetrieval";

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
});

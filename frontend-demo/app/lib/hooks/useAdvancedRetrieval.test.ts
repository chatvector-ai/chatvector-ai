import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAdvancedRetrieval } from "./useAdvancedRetrieval";
import { EMPTY_ADVANCED_RETRIEVAL, loadAdvancedRetrievalState } from "../advancedRetrieval";

const STORAGE_KEY = "chatvector-advanced-retrieval-explicit";

describe("useAdvancedRetrieval", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("resetExplicitOverrides clears in-memory state and sessionStorage", async () => {
    const { result } = renderHook(() => useAdvancedRetrieval());

    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      result.current.setHybridEnabled(true);
      result.current.setScope("tenant");
    });

    expect(result.current.state.explicit).toEqual({
      hybridEnabled: true,
      scope: "tenant",
    });
    expect(sessionStorage.getItem(STORAGE_KEY)).not.toBeNull();

    act(() => {
      result.current.resetExplicitOverrides();
    });

    expect(result.current.state).toEqual(EMPTY_ADVANCED_RETRIEVAL);
    expect(loadAdvancedRetrievalState()).toEqual(EMPTY_ADVANCED_RETRIEVAL);
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("reload restores overrides that were saved before reset on another mount", async () => {
    const first = renderHook(() => useAdvancedRetrieval());
    await act(async () => {
      await Promise.resolve();
    });

    act(() => {
      first.result.current.setHybridEnabled(true);
    });
    first.unmount();

    const second = renderHook(() => useAdvancedRetrieval());
    await act(async () => {
      await Promise.resolve();
    });

    expect(second.result.current.state.explicit.hybridEnabled).toBe(true);
  });
});
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  clampMatchCount,
  DEFAULT_RETRIEVAL_SETTINGS,
  loadRetrievalSettings,
  saveRetrievalSettings,
} from "./retrievalSettings";

const STORAGE_KEY = "chatvector-retrieval-settings";

describe("clampMatchCount", () => {
  it("clamps values to 1–20", () => {
    expect(clampMatchCount(0)).toBe(1);
    expect(clampMatchCount(21)).toBe(20);
    expect(clampMatchCount(7.6)).toBe(8);
    expect(clampMatchCount(Number.NaN)).toBe(5);
  });
});

describe("retrieval settings persistence", () => {
  const storage = new Map<string, string>();

  beforeEach(() => {
    storage.clear();
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      removeItem: (key: string) => {
        storage.delete(key);
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns defaults when nothing is stored", () => {
    expect(loadRetrievalSettings()).toEqual(DEFAULT_RETRIEVAL_SETTINGS);
  });

  it("round-trips valid settings through sessionStorage", () => {
    const settings = { scope: "tenant" as const, matchCount: 12 };
    saveRetrievalSettings(settings);
    expect(loadRetrievalSettings()).toEqual(settings);
    expect(storage.get(STORAGE_KEY)).toBe(JSON.stringify(settings));
  });

  it("clamps invalid stored match counts", () => {
    storage.set(STORAGE_KEY, JSON.stringify({ scope: "session", matchCount: 99 }));
    expect(loadRetrievalSettings().matchCount).toBe(20);
  });

  it("falls back to defaults for invalid stored scope", () => {
    storage.set(STORAGE_KEY, JSON.stringify({ scope: "global", matchCount: 5 }));
    expect(loadRetrievalSettings()).toEqual(DEFAULT_RETRIEVAL_SETTINGS);
  });
});

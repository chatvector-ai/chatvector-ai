import { describe, it, expect, beforeEach } from "vitest";
import {
  getSessionActiveDocumentKey,
  getStoredActiveDocumentId,
  setStoredActiveDocumentId,
  clearStoredActiveDocumentId,
} from "./documentStore";

describe("documentStore activeDocumentId session persistence", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("computes the active document storage key", () => {
    expect(getSessionActiveDocumentKey("session-123")).toBe(
      "chatvector_active_doc_session-123",
    );
  });

  it("returns null when no active document is stored", () => {
    expect(getStoredActiveDocumentId("session-123")).toBeNull();
  });

  it("stores, retrieves, and clears active document id", () => {
    setStoredActiveDocumentId("session-123", "doc-456");
    expect(getStoredActiveDocumentId("session-123")).toBe("doc-456");
    expect(
      sessionStorage.getItem(getSessionActiveDocumentKey("session-123")),
    ).toBe("doc-456");

    clearStoredActiveDocumentId("session-123");
    expect(getStoredActiveDocumentId("session-123")).toBeNull();
    expect(
      sessionStorage.getItem(getSessionActiveDocumentKey("session-123")),
    ).toBeNull();
  });

  it("handles empty or blank documentId gracefully by removing key", () => {
    setStoredActiveDocumentId("session-123", "doc-456");
    setStoredActiveDocumentId("session-123", "");
    expect(getStoredActiveDocumentId("session-123")).toBeNull();
  });
});

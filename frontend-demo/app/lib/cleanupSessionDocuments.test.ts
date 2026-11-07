import { describe, it, expect, vi, beforeEach } from "vitest";
import { cleanupSessionDocuments } from "./cleanupSessionDocuments";

vi.mock("./api", () => ({
  getSession: vi.fn(),
  deleteDocument: vi.fn(),
}));

vi.mock("./documentStore", () => ({
  removeUploadedDocument: vi.fn(),
}));

import { deleteDocument, getSession } from "./api";
import { removeUploadedDocument } from "./documentStore";

describe("cleanupSessionDocuments", () => {
  beforeEach(() => {
    vi.mocked(getSession).mockReset();
    vi.mocked(deleteDocument).mockReset();
    vi.mocked(removeUploadedDocument).mockReset();
  });

  it("deletes bound documents and removes them from local storage", async () => {
    vi.mocked(getSession).mockResolvedValue({
      id: "session-1",
      created_at: "2026-01-01T00:00:00Z",
      last_active: "2026-01-01T00:00:00Z",
      metadata: {},
      document_ids: ["doc-a", "doc-b"],
      display_label: "New session",
    });
    vi.mocked(deleteDocument).mockResolvedValue({ status: "gone" });

    await cleanupSessionDocuments("session-1");

    expect(deleteDocument).toHaveBeenCalledWith("doc-a");
    expect(deleteDocument).toHaveBeenCalledWith("doc-b");
    expect(removeUploadedDocument).toHaveBeenCalledWith("doc-a");
    expect(removeUploadedDocument).toHaveBeenCalledWith("doc-b");
  });

  it("drops local entries when the document is still processing", async () => {
    vi.mocked(getSession).mockResolvedValue({
      id: "session-1",
      created_at: "2026-01-01T00:00:00Z",
      last_active: "2026-01-01T00:00:00Z",
      metadata: {},
      document_ids: ["doc-processing"],
      display_label: "New session",
    });
    vi.mocked(deleteDocument).mockResolvedValue({
      status: "conflict",
      message: "Document cannot be deleted while in the 'embedding' state.",
    });

    await cleanupSessionDocuments("session-1");

    expect(removeUploadedDocument).toHaveBeenCalledWith("doc-processing");
  });

  it("ignores sessions that cannot be loaded", async () => {
    vi.mocked(getSession).mockRejectedValue(new Error("not found"));

    await cleanupSessionDocuments("missing-session");

    expect(deleteDocument).not.toHaveBeenCalled();
    expect(removeUploadedDocument).not.toHaveBeenCalled();
  });
});

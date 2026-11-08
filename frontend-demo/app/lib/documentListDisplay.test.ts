import { describe, expect, it } from "vitest";
import {
  documentFailureDetail,
  fileTypeFromFileName,
  isDocumentInActiveScope,
  isRetrievalScopeMembershipDefinite,
  sessionDocumentRows,
} from "./documentListDisplay";

describe("fileTypeFromFileName", () => {
  it("uses the extension when present", () => {
    expect(fileTypeFromFileName("notes.PDF")).toBe("pdf");
  });

  it('returns "file" when the name has no extension', () => {
    expect(fileTypeFromFileName("README")).toBe("file");
  });
});

describe("documentFailureDetail", () => {
  it("shows stage and message for failed documents", () => {
    expect(
      documentFailureDetail("failed", {
        stage: "embedding",
        message: "timed out",
      })
    ).toBe("embedding: timed out");
  });

  it("returns null for completed documents", () => {
    expect(
      documentFailureDetail("completed", { stage: "embedding", message: "x" })
    ).toBeNull();
  });
});

describe("isDocumentInActiveScope", () => {
  it("marks only the selected id in session scope", () => {
    const base = {
      scope: "session" as const,
      scopeIsExplicit: true,
      selectedDocumentId: "doc-a",
    };
    expect(
      isDocumentInActiveScope({
        ...base,
        documentId: "doc-a",
        status: "completed",
      })
    ).toBe(true);
    expect(
      isDocumentInActiveScope({
        ...base,
        documentId: "doc-b",
        status: "completed",
      })
    ).toBe(false);
  });

  it("marks completed documents in tenant scope", () => {
    expect(
      isDocumentInActiveScope({
        scope: "tenant",
        scopeIsExplicit: true,
        selectedDocumentId: null,
        documentId: "doc-1",
        status: "completed",
      })
    ).toBe(true);
    expect(
      isDocumentInActiveScope({
        scope: "tenant",
        scopeIsExplicit: true,
        selectedDocumentId: null,
        documentId: "doc-2",
        status: "processing",
      })
    ).toBe(false);
  });

  it("returns null when scope is not explicit", () => {
    expect(
      isDocumentInActiveScope({
        scope: "session",
        scopeIsExplicit: false,
        selectedDocumentId: "doc-a",
        documentId: "doc-a",
        status: "completed",
      })
    ).toBeNull();
  });
});

describe("isRetrievalScopeMembershipDefinite", () => {
  it("is indefinite when a preset is selected without an explicit scope", () => {
    expect(
      isRetrievalScopeMembershipDefinite({ explicit: { preset: "eval_hybrid" } })
    ).toBe(false);
    expect(
      isRetrievalScopeMembershipDefinite({
        explicit: { preset: "eval_hybrid", scope: "tenant" },
      })
    ).toBe(true);
  });
});

describe("sessionDocumentRows", () => {
  it("joins session ids to summaries and marks missing docs unavailable", () => {
    const rows = sessionDocumentRows(
      ["doc-1", "doc-missing"],
      [
        {
          document_id: "doc-1",
          file_name: "a.txt",
          status: "completed",
          created_at: null,
          updated_at: null,
        },
      ]
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ kind: "summary", documentId: "doc-1" });
    expect(rows[1]).toEqual({ kind: "unavailable", documentId: "doc-missing" });
  });
});

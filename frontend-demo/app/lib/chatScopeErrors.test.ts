import { describe, expect, it } from "vitest";
import { mapChatTurnError } from "./chatScopeErrors";

const BACKEND_MESSAGE =
  "The requested document is not in the retrieval scope after applying metadata_filter.";

describe("mapChatTurnError", () => {
  it("names the active document for anchor_document_excluded_by_filter", () => {
    const mapped = mapChatTurnError(
      {
        code: "anchor_document_excluded_by_filter",
        message: BACKEND_MESSAGE,
      },
      "notes.pdf",
    );

    expect(mapped.message).toContain("notes.pdf");
    expect(mapped.message).toMatch(/session scope/i);
    expect(mapped.message).toMatch(/clear or change the filter/i);
    expect(mapped.code).toBe("anchor_document_excluded_by_filter");
  });

  it("falls back to the backend message when the filename is unknown", () => {
    const error = {
      code: "anchor_document_excluded_by_filter",
      message: BACKEND_MESSAGE,
    };

    expect(mapChatTurnError(error)).toEqual(error);
    expect(mapChatTurnError(error, "   ")).toEqual(error);
  });

  it("leaves other error codes unchanged", () => {
    const error = {
      code: "no_documents_in_scope",
      message: "No documents available for retrieval in the requested scope.",
    };

    expect(mapChatTurnError(error, "notes.pdf")).toEqual(error);
  });
});
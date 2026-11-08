import { describe, expect, it } from "vitest";
import {
  buildMetadataFromRows,
  formatDocumentMetadataLines,
  isDocumentScalarMetadata,
  parseDocumentScalarMetadata,
  parseMetadataValue,
} from "./documentMetadata";

describe("documentMetadata", () => {
  it("parses scalar metadata objects and rejects non-scalars", () => {
    expect(parseDocumentScalarMetadata({ department: "legal", year: 2026 })).toEqual({
      department: "legal",
      year: 2026,
    });
    expect(parseDocumentScalarMetadata({ nested: { a: 1 } })).toBeUndefined();
    expect(isDocumentScalarMetadata({ ok: true })).toBe(true);
  });

  it("coerces metadata row values", () => {
    expect(parseMetadataValue("legal")).toBe("legal");
    expect(parseMetadataValue("42")).toBe(42);
    expect(parseMetadataValue("true")).toBe(true);
    expect(buildMetadataFromRows([{ key: "department", value: "legal" }])).toEqual({
      department: "legal",
    });
  });

  it("formats stored metadata for display", () => {
    expect(
      formatDocumentMetadataLines({ department: "legal", year: 2026 }),
    ).toEqual(["department=legal", "year=2026"]);
  });
});

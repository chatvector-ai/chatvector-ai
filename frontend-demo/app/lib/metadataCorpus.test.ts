import { describe, expect, it } from "vitest";
import {
  collectMetadataKeys,
  distinctMetadataValuesForKey,
  parseStoredMetadataFilter,
  type MetadataCorpusDocument,
} from "./metadataCorpus";

describe("metadataCorpus", () => {
  const corpus: MetadataCorpusDocument[] = [
    { metadata: { department: "legal", year: 2024 } },
    { metadata: { department: "hr", active: true } },
    {},
  ];

  it("collects sorted keys from document metadata", () => {
    expect(collectMetadataKeys(corpus)).toEqual(["active", "department", "year"]);
  });

  it("returns no keys when the corpus has no metadata", () => {
    expect(collectMetadataKeys([{}, { metadata: undefined }])).toEqual([]);
  });

  it("lists distinct values for a key preserving scalar types", () => {
    expect(distinctMetadataValuesForKey(corpus, "department")).toEqual([
      "hr",
      "legal",
    ]);
    expect(distinctMetadataValuesForKey(corpus, "active")).toEqual([true]);
  });

  it("parses stored metadata filters and rejects invalid shapes", () => {
    expect(parseStoredMetadataFilter({ department: "legal" })).toEqual({
      department: "legal",
    });
    expect(parseStoredMetadataFilter({ department: { in: ["a"] } })).toBeUndefined();
    expect(parseStoredMetadataFilter([])).toBeUndefined();
  });
});

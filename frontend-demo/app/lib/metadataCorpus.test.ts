import { describe, expect, it } from "vitest";
import {
  collectMetadataKeys,
  distinctMetadataValuesForKey,
  metadataCorpusForSessionDocuments,
  metadataCorpusFromDocumentList,
  parseStoredMetadataFilter,
  type MetadataCorpusDocument,
  type MetadataCorpusSourceDocument,
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

  it("builds tenant and session corpora from document lists", () => {
    const documents: MetadataCorpusSourceDocument[] = [
      {
        document_id: "doc-1",
        metadata: { department: "legal" },
      },
      {
        document_id: "doc-2",
        metadata: { region: "us" },
      },
      { document_id: "doc-3" },
    ];

    expect(metadataCorpusFromDocumentList(documents)).toEqual([
      { metadata: { department: "legal" } },
      { metadata: { region: "us" } },
      {},
    ]);
    expect(
      collectMetadataKeys(
        metadataCorpusForSessionDocuments(["doc-2", "doc-1", "missing"], documents)
      )
    ).toEqual(["department", "region"]);
  });

  it("parses stored metadata filters and rejects invalid shapes", () => {
    expect(parseStoredMetadataFilter({ department: "legal" })).toEqual({
      department: "legal",
    });
    expect(parseStoredMetadataFilter({ department: { in: ["a"] } })).toBeUndefined();
    expect(parseStoredMetadataFilter([])).toBeUndefined();
  });
});

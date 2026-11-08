import {
  type DocumentScalarMetadata,
  isDocumentScalarMetadata,
} from "./documentMetadata";

export type MetadataCorpusDocument = {
  metadata?: DocumentScalarMetadata;
};

export type MetadataCorpusSourceDocument = {
  document_id: string;
  metadata?: DocumentScalarMetadata;
};

export function metadataCorpusFromDocumentList(
  documents: Array<{ metadata?: DocumentScalarMetadata }>
): MetadataCorpusDocument[] {
  return documents.map((doc) =>
    doc.metadata !== undefined ? { metadata: doc.metadata } : {}
  );
}

export function metadataCorpusForSessionDocuments(
  documentIds: string[],
  documents: MetadataCorpusSourceDocument[]
): MetadataCorpusDocument[] {
  const byId = new Map(documents.map((doc) => [doc.document_id, doc]));
  return documentIds.map((documentId) => {
    const doc = byId.get(documentId);
    return doc?.metadata !== undefined ? { metadata: doc.metadata } : {};
  });
}

function scalarLabel(value: string | number | boolean): string {
  return String(value);
}

export function collectMetadataKeys(
  documents: MetadataCorpusDocument[]
): string[] {
  const keys = new Set<string>();
  for (const doc of documents) {
    if (!doc.metadata) continue;
    for (const key of Object.keys(doc.metadata)) {
      keys.add(key);
    }
  }
  return Array.from(keys).sort((a, b) => a.localeCompare(b));
}

export function distinctMetadataValuesForKey(
  documents: MetadataCorpusDocument[],
  key: string
): Array<string | number | boolean> {
  const seen = new Map<string, string | number | boolean>();
  for (const doc of documents) {
    if (!doc.metadata || !(key in doc.metadata)) continue;
    const value = doc.metadata[key];
    const label = scalarLabel(value);
    if (!seen.has(label)) {
      seen.set(label, value);
    }
  }
  return Array.from(seen.values()).sort((a, b) =>
    scalarLabel(a).localeCompare(scalarLabel(b))
  );
}

export function parseStoredMetadataFilter(
  raw: unknown
): DocumentScalarMetadata | undefined {
  if (!isDocumentScalarMetadata(raw) || Object.keys(raw).length === 0) {
    return undefined;
  }
  return { ...raw };
}

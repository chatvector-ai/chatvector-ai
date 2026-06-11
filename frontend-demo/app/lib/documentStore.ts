const STORAGE_KEY = "chatvector_uploaded_documents";
const MAX_ENTRIES = 50;

export type StoredDocument = {
  documentId: string;
  fileName: string;
  uploadedAt: number;
};

function isStoredDocument(value: unknown): value is StoredDocument {
  if (value == null || typeof value !== "object") return false;
  const o = value as Record<string, unknown>;
  return (
    typeof o.documentId === "string" &&
    o.documentId.length > 0 &&
    typeof o.fileName === "string" &&
    typeof o.uploadedAt === "number"
  );
}

function read(): StoredDocument[] {
  if (typeof window === "undefined") return [];
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isStoredDocument);
  } catch (e) {
    console.warn("Failed to parse uploaded documents from localStorage", e);
    return [];
  }
}

function write(documents: StoredDocument[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(documents));
}

export function getUploadedDocuments(): StoredDocument[] {
  return read().sort((a, b) => b.uploadedAt - a.uploadedAt);
}

export function saveUploadedDocument(doc: {
  documentId: string;
  fileName: string;
}): void {
  if (!doc.documentId) return;
  const existing = read().filter((d) => d.documentId !== doc.documentId);
  const next: StoredDocument[] = [
    { documentId: doc.documentId, fileName: doc.fileName, uploadedAt: Date.now() },
    ...existing,
  ].slice(0, MAX_ENTRIES);
  write(next);
}

export function removeUploadedDocument(documentId: string): void {
  if (!documentId) return;
  write(read().filter((d) => d.documentId !== documentId));
}

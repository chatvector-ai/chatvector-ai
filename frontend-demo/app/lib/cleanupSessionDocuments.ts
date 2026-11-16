import { deleteDocument, getSession } from "./api";
import { removeUploadedDocument, clearStoredActiveDocumentId } from "./documentStore";

/**
 * Demo-only: delete documents bound to a session and drop them from the
 * browser document registry so batch does not keep stale entries.
 */
export async function cleanupSessionDocuments(sessionId: string): Promise<void> {
  clearStoredActiveDocumentId(sessionId);
  let documentIds: string[] = [];

  try {
    const session = await getSession(sessionId);
    documentIds = [...new Set(session.document_ids)];
  } catch {
    return;
  }

  for (const documentId of documentIds) {
    try {
      const result = await deleteDocument(documentId);
      if (result.status === "gone" || result.status === "conflict") {
        removeUploadedDocument(documentId);
      }
    } catch {
      /* best effort — session delete should still proceed */
    }
  }
}

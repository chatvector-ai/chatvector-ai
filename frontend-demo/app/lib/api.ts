const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function deleteDocument(
  documentId: string
): Promise<"gone" | "conflict" | "error"> {
  const res = await fetch(`${API_BASE}/documents/${documentId}`, { method: "DELETE" });
  if (res.status === 204 || res.status === 404) return "gone";
  if (res.status === 409) return "conflict";
  return "error";
}

export class DocumentNotFoundError extends Error {
  readonly code = "document_not_found" as const;
  constructor() {
    super("Document not found.");
    this.name = "DocumentNotFoundError";
  }
}

export async function getDocumentStatus(
  statusEndpoint: string
): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}${statusEndpoint}`);
  if (res.status === 404) throw new DocumentNotFoundError();
  if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
  const data = await res.json();
  return { status: String(data?.status ?? "") };
}

export async function uploadDocument(
  file: File
): Promise<{ documentId: string; statusEndpoint: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    let message = "Upload failed. Please try again.";
    try {
      const errBody = await res.json();
      const detail = errBody?.detail;
      if (typeof detail?.message === "string") message = detail.message;
    } catch {
      /* ignore */
    }
    throw new Error(message);
  }
  const data = await res.json();
  const documentId = data?.document_id as string | undefined;
  const statusEndpoint = data?.status_endpoint as string | undefined;
  if (!documentId || !statusEndpoint) {
    throw new Error("Invalid upload response from server.");
  }
  return { documentId, statusEndpoint };
}

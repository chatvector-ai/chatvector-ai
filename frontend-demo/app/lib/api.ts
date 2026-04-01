const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ChatSource = {
  file_name: string;
  page_number: number | null;
  chunk_index: number | null;
};

export type ChatResponse = {
  question: string;
  chunks: number;
  answer: string;
  sources: ChatSource[];
};

export class ChatError extends Error {
  constructor(
    public readonly code: "no_document" | "backend_unreachable" | "unexpected",
    message: string
  ) {
    super(message);
    this.name = "ChatError";
  }
}

export async function sendMessage(
  question: string,
  docId: string,
  matchCount = 5
): Promise<ChatResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, doc_id: docId, match_count: matchCount }),
    });
  } catch {
    throw new ChatError(
      "backend_unreachable",
      "Cannot reach the server. Check your connection."
    );
  }

  if (res.status === 404) {
    throw new ChatError(
      "no_document",
      "Document not found. It may have been deleted."
    );
  }

  if (!res.ok) {
    throw new ChatError(
      "unexpected",
      `Server error (${res.status}). Please try again.`
    );
  }

  return (await res.json()) as ChatResponse;
}

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

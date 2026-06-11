import { getSessionId } from "./session";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ChatSource = {
  file_name: string;
  page_number: number | null;
  chunk_index: number | null;
};

export type Message = {
  id: number;
  sender: "user" | "ai";
  text: string;
  document_id?: string;
  sources?: ChatSource[];
  chunks?: number;
};

export type ChatResponse = {
  question: string;
  chunks: number;
  answer: string;
  sources: ChatSource[];
  status?: "ok" | "error";
  error?: { code: ChatErrorCode; message: string };
};

export type ChatErrorCode =
  | "llm_missing_api_key"
  | "llm_invalid_api_key"
  | "llm_rate_limited"
  | "llm_timeout_or_connection"
  | "llm_unexpected";

const CHAT_ERROR_MESSAGES: Record<ChatErrorCode, string> = {
  llm_missing_api_key:
    "No API key is configured. Check your `LLM_API_KEY` environment variable.",
  llm_invalid_api_key:
    "The configured API key was rejected. Verify your `LLM_API_KEY` is correct.",
  llm_rate_limited:
    "The LLM provider is rate limiting requests. Try again in a moment.",
  llm_timeout_or_connection:
    "The LLM provider timed out. Check your network and try again.",
  llm_unexpected: "An unexpected error occurred with the LLM provider.",
};

export class ChatError extends Error {
  constructor(
    public readonly code:
      | "no_document"
      | "backend_unreachable"
      | "unexpected"
      | ChatErrorCode,
    message: string
  ) {
    super(message);
    this.name = "ChatError";
  }
}

function isChatErrorCode(code: unknown): code is ChatErrorCode {
  return typeof code === "string" && code in CHAT_ERROR_MESSAGES;
}

function toSoftLlmChatError(error?: ChatResponse["error"]): ChatError {
  const code = isChatErrorCode(error?.code) ? error.code : "llm_unexpected";
  return new ChatError(code, CHAT_ERROR_MESSAGES[code]);
}

export async function sendMessage(
  question: string,
  docId: string,
  matchCount = 5,
  sessionIdOverride?: string | null
): Promise<ChatResponse> {
  const sessionId = sessionIdOverride !== undefined ? sessionIdOverride : getSessionId();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const body: Record<string, string | number> = {
    question,
    doc_id: docId,
    match_count: matchCount,
  };

  if (sessionId !== null) {
    headers["X-Session-Id"] = sessionId;
    body.session_id = sessionId;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
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

  const response = (await res.json()) as ChatResponse;
  if (response.status === "error") {
    throw toSoftLlmChatError(response.error);
  }

  return response;
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

export type AttachmentState = {
  fileName: string;
  documentId: string;
  statusEndpoint: string;
  status: "processing" | "ready" | "failed";
  stage?: string;
  chunks?: { total: number; processed: number };
};

export type DocumentStatusPayload = {
  status: string;
  stage?: string;
  error?: { stage?: string; message?: string };
  chunks?: { total: number; processed: number } | null;
  created_at?: string | null;
  updated_at?: string | null;
};

function parseChunks(raw: unknown): { total: number; processed: number } | undefined {
  if (raw == null || typeof raw !== "object") return undefined;
  const o = raw as Record<string, unknown>;
  const total = o.total;
  const processed = o.processed;
  if (typeof total !== "number" || typeof processed !== "number") return undefined;
  return { total, processed };
}

export async function getDocumentStatus(
  statusEndpoint: string
): Promise<DocumentStatusPayload> {
  const res = await fetch(`${API_BASE}${statusEndpoint}`);
  if (res.status === 404) throw new DocumentNotFoundError();
  if (!res.ok) throw new Error(`Status check failed: ${res.status}`);
  const data = (await res.json()) as Record<string, unknown>;
  const status = String(data?.status ?? "");
  const stageRaw = data?.stage;
  const stage =
    typeof stageRaw === "string" && stageRaw.length > 0 ? stageRaw : undefined;
  const chunks = parseChunks(data?.chunks);
  const errorRaw = data?.error;
  const error =
    errorRaw != null && typeof errorRaw === "object"
      ? { stage: (errorRaw as Record<string, unknown>).stage as string | undefined,
        message: (errorRaw as Record<string, unknown>).message as string | undefined
       }
      : undefined;
  const createdAt = data?.created_at as string | null | undefined;
  const updatedAt = data?.updated_at as string | null | undefined;
  return {
    status,
    ...(stage !== undefined ? { stage } : {}),
    ...(error !== undefined ? { error } : {}),
    ...(chunks !== undefined ? { chunks } : {}),
    ...(createdAt !== undefined ? { created_at: createdAt } : {}),
    ...(updatedAt !== undefined ? { updated_at: updatedAt } : {}),
  };
}

export async function uploadDocument(
  file: File
): Promise<{ documentId: string; statusEndpoint: string }> {
  const sessionId = getSessionId();
  const formData = new FormData();
  formData.append("file", file);
  
  const headers: Record<string, string> = {};
  if (sessionId !== null) {
    headers["X-Session-Id"] = sessionId;
  }

  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    headers,
    body: formData,
  });
  
  if (!res.ok) {
    if (res.status === 429) {
      throw new Error("Too many requests — please wait a moment and try again.");
    }
    let message = "Upload failed. Please try again.";
    try {
      const errBody = await res.json();
      const detail = errBody?.detail;
      if (typeof detail?.message === "string") message = detail.message;
      else if (typeof detail === "string") message = detail;
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

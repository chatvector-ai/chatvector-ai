import {
  backendApiErrorFromResponse,
  formatBackendErrorMessage,
  isGenericBackendError,
  parseBackendErrorBody,
  type BackendErrorField,
} from "./apiErrors";
import {
  clampMatchCount,
  DEFAULT_MATCH_COUNT,
  type RetrievalScope,
} from "./retrievalSettings";
import { getSessionId } from "./session";
import { parseSSEStream, type StreamEvent } from "./stream";

export type { StreamEvent } from "./stream";

export type { RetrievalScope } from "./retrievalSettings";
export type { BackendErrorField } from "./apiErrors";
export { BackendApiError } from "./apiErrors";

export type ChatCallOptions = {
  matchCount?: number;
  scope?: RetrievalScope;
  sessionId?: string | null;
};

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * ChatVector API key for the frontend demo.
 *
 * This is read from NEXT_PUBLIC_CHATVECTOR_API_KEY at build time and is
 * visible to anyone who inspects the browser bundle.  It is intended only
 * for local development and demonstration purposes — do NOT use a
 * production key here.  For production deployments, proxy all API requests
 * through a server-side component or Next.js Route Handler so the key stays
 * server-side and out of the client bundle.
 *
 * When the variable is not set the frontend operates without authentication,
 * which only works when the backend is running with APP_ENV=development.
 */
const DEMO_API_KEY = process.env.NEXT_PUBLIC_CHATVECTOR_API_KEY ?? "";

export function authHeaders(): Record<string, string> {
  if (!DEMO_API_KEY) return {};
  return { Authorization: `Bearer ${DEMO_API_KEY}` };
}

export type ChatSource = {
  file_name: string;
  page_number: number | null;
  chunk_index: number | null;
  score?: number | null;
  score_type?: string | null;
};

/** Opt-in retrieval debug metadata when the backend exposes it. */
export type RetrievalDebugMetadata = {
  original_query?: string;
  transformed_queries?: string[];
  transformation_strategy?: string;
};

export type RetrievalInspectorData = {
  question?: string;
  retrieval_debug?: RetrievalDebugMetadata;
  sources?: ChatSource[];
  chunks?: number;
  model?: string;
  latency_ms?: number;
};

export type Message = {
  id: number;
  sender: "user" | "ai";
  text: string;
  document_id?: string;
  question?: string;
  retrieval_debug?: RetrievalDebugMetadata;
  sources?: ChatSource[];
  chunks?: number;
  latency_ms?: number;
  model?: string;
  error?: { code: string; message: string };
  /** True while real SSE tokens are in flight for this message. */
  isStreaming?: boolean;
};

export type ChatResponse = {
  question: string;
  chunks: number;
  answer: string;
  sources: ChatSource[];
  doc_id?: string;
  latency_ms?: number;
  model?: string;
  retrieval_debug?: RetrievalDebugMetadata;
  status?: "ok" | "error";
  error?: { code: ChatErrorCode | string; message: string };
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
      | "api_error"
      | "rate_limited"
      | ChatErrorCode,
    message: string,
    public readonly fields?: BackendErrorField[],
    public readonly backendCode?: string
  ) {
    super(message);
    this.name = "ChatError";
  }
}

/**
 * Thrown when the backend returns 400 with `streaming_disabled`.
 * The caller should catch this and fall back to the sync `sendMessage()` path.
 */
export class StreamingDisabledError extends Error {
  readonly code = "streaming_disabled" as const;
  constructor() {
    super("Streaming responses are currently disabled.");
    this.name = "StreamingDisabledError";
  }
}

function isChatErrorCode(code: unknown): code is ChatErrorCode {
  return typeof code === "string" && code in CHAT_ERROR_MESSAGES;
}

const DOCUMENT_NOT_FOUND_MESSAGE =
  "Document not found. It may have been deleted.";
const RATE_LIMITED_MESSAGE =
  "Too many requests — please wait a moment and try again.";
const DELETE_CONFLICT_MESSAGE =
  "Can't remove while the document is queued or processing.";
const DELETE_ERROR_MESSAGE = "Could not remove the document. Try again.";

function httpErrorFallback(res: Response): string | undefined {
  if (res.status === 404) return DOCUMENT_NOT_FOUND_MESSAGE;
  if (res.status === 429) return RATE_LIMITED_MESSAGE;
  return undefined;
}

export function softFailureMessage(error?: ChatResponse["error"]): string {
  if (!error) {
    return CHAT_ERROR_MESSAGES.llm_unexpected;
  }
  if (isChatErrorCode(error.code)) {
    return CHAT_ERROR_MESSAGES[error.code];
  }
  return error.message || CHAT_ERROR_MESSAGES.llm_unexpected;
}

async function throwChatHttpError(res: Response): Promise<never> {
  const apiError = await backendApiErrorFromResponse(res, httpErrorFallback(res));
  const { parsed } = apiError;

  if (res.status === 404) {
    throw new ChatError(
      "no_document",
      apiError.message,
      parsed.fields,
      parsed.code
    );
  }
  if (res.status === 429 || parsed.code === "rate_limited") {
    throw new ChatError(
      "rate_limited",
      apiError.message,
      parsed.fields,
      parsed.code
    );
  }
  throw new ChatError(
    "api_error",
    apiError.message,
    parsed.fields,
    parsed.code
  );
}

export async function sendMessage(
  question: string,
  docId: string,
  options: ChatCallOptions = {}
): Promise<ChatResponse> {
  const sessionId =
    options.sessionId !== undefined ? options.sessionId : getSessionId();
  const matchCount = clampMatchCount(options.matchCount ?? DEFAULT_MATCH_COUNT);
  const scope = options.scope ?? "session";

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...authHeaders(),
  };
  const body: Record<string, string | number> = {
    question,
    doc_id: docId,
    match_count: matchCount,
    scope,
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

  if (!res.ok) {
    await throwChatHttpError(res);
  }

  const response = (await res.json()) as ChatResponse;
  return response;
}

/**
 * Send a chat question via `POST /chat/stream` and return an async generator
 * that yields SSE `StreamEvent` objects as they arrive.
 *
 * Throws `StreamingDisabledError` when the backend has streaming turned off
 * (HTTP 400, `streaming_disabled`), allowing the caller to fall back to the
 * synchronous `sendMessage()` path transparently.
 *
 * @param signal  Optional `AbortSignal` from an `AbortController` to cancel
 *                the stream (e.g. a "Stop generating" button).
 */
export async function* sendMessageStream(
  question: string,
  docId: string,
  options: ChatCallOptions = {},
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const sessionId =
    options.sessionId !== undefined ? options.sessionId : getSessionId();
  const matchCount = clampMatchCount(options.matchCount ?? DEFAULT_MATCH_COUNT);
  const scope = options.scope ?? "session";

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...authHeaders(),
  };
  const body: Record<string, string | number> = {
    question,
    doc_id: docId,
    match_count: matchCount,
    scope,
  };

  if (sessionId !== null) {
    headers["X-Session-Id"] = sessionId;
    body.session_id = sessionId;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    // AbortError should propagate so callers can distinguish cancellation.
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ChatError(
      "backend_unreachable",
      "Cannot reach the server. Check your connection."
    );
  }

  // Handle streaming_disabled: 400 with { detail: { code: "streaming_disabled" } }
  if (res.status === 400) {
    try {
      const errBody = await res.json();
      if (errBody?.detail?.code === "streaming_disabled") {
        throw new StreamingDisabledError();
      }
    } catch (e) {
      if (e instanceof StreamingDisabledError) throw e;
    }
  }

  if (!res.ok) {
    await throwChatHttpError(res);
  }

  if (!res.body) {
    throw new ChatError("unexpected", "No response body for stream.");
  }

  yield* parseSSEStream(res.body, signal);
}

export type DeleteDocumentResult =
  | { status: "gone" }
  | { status: "conflict"; message: string }
  | { status: "error"; message: string };

export async function deleteDocument(
  documentId: string
): Promise<DeleteDocumentResult> {
  const res = await fetch(`${API_BASE}/documents/${documentId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (res.status === 204 || res.status === 404) return { status: "gone" };
  if (res.status === 409) {
    const apiError = await backendApiErrorFromResponse(
      res,
      DELETE_CONFLICT_MESSAGE
    );
    return { status: "conflict", message: apiError.message };
  }
  const apiError = await backendApiErrorFromResponse(res, DELETE_ERROR_MESSAGE);
  return { status: "error", message: apiError.message };
}

export class DocumentNotFoundError extends Error {
  readonly code = "document_not_found" as const;
  constructor(message = "Document not found.") {
    super(message);
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
  queue_position?: number;
};

export type DocumentStatusPayload = {
  status: string;
  stage?: string;
  error?: { stage?: string; message?: string };
  chunks?: { total: number; processed: number } | null;
  created_at?: string | null;
  updated_at?: string | null;
  /**
   * Live queue position reported by the backend while the document is still
   * waiting in the ingestion queue (status === "queued"). Numbered 1 = next to
   * be processed. Optional because non-queued responses omit the field.
   */
  queue_position?: number;
};

function parseChunks(raw: unknown): { total: number; processed: number } | undefined {
  if (raw == null || typeof raw !== "object") return undefined;
  const o = raw as Record<string, unknown>;
  const total = o.total;
  const processed = o.processed;
  if (typeof total !== "number" || typeof processed !== "number") return undefined;
  return { total, processed };
}

/**
 * Extract a queue position from a status payload. Only positive integers
 * count — non-numeric, negative, or zero values are dropped so the UI never
 * shows a phantom "Position 0" indicator.
 */
function parseQueuePosition(raw: unknown): number | undefined {
  if (typeof raw !== "number" || !Number.isFinite(raw)) return undefined;
  if (!Number.isInteger(raw) || raw < 1) return undefined;
  return raw;
}

export async function getDocumentStatus(
  statusEndpoint: string
): Promise<DocumentStatusPayload> {
  const res = await fetch(`${API_BASE}${statusEndpoint}`, { headers: authHeaders() });
  if (res.status === 404) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* ignore non-JSON 404 bodies */
    }
    const parsed = parseBackendErrorBody(body);
    const message = isGenericBackendError(parsed)
      ? "Document not found."
      : formatBackendErrorMessage(parsed);
    throw new DocumentNotFoundError(message);
  }
  if (!res.ok) {
    throw await backendApiErrorFromResponse(
      res,
      `Status check failed: ${res.status}`
    );
  }
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
  const queuePosition = parseQueuePosition(data?.queue_position);
  return {
    status,
    ...(stage !== undefined ? { stage } : {}),
    ...(error !== undefined ? { error } : {}),
    ...(chunks !== undefined ? { chunks } : {}),
    ...(createdAt !== undefined ? { created_at: createdAt } : {}),
    ...(updatedAt !== undefined ? { updated_at: updatedAt } : {}),
    ...(queuePosition !== undefined ? { queue_position: queuePosition } : {}),
  };
}

export type BatchResultItem = {
  status: "ok" | "error";
  question: string;
  doc_ids: string[];
  chunks?: number;
  answer?: string;
  sources?: ChatSource[];
  latency_ms?: number;
  model?: string;
  retrieval_debug?: RetrievalDebugMetadata;
  session_id?: string;
  error?: { code: string; message: string };
};

export type BatchChatResponse = {
  count: number;
  success_count: number;
  failure_count: number;
  results: BatchResultItem[];
};

/**
 * Query the same question against several documents in one request via
 * `POST /chat/batch`. Each document becomes its own query item, so the response
 * contains one result per document (in the same order as `docIds`).
 */
export async function sendBatchMessage(
  question: string,
  docIds: string[],
  options: ChatCallOptions = {}
): Promise<BatchChatResponse> {
  const matchCount = clampMatchCount(options.matchCount ?? DEFAULT_MATCH_COUNT);
  const scope = options.scope ?? "session";

  return postBatchChat(
    {
      scope,
      queries: docIds.map((docId) => ({
        question,
        doc_ids: [docId],
        match_count: matchCount,
      })),
    },
    options.sessionId
  );
}

/**
 * Ask one question across multiple documents in a single batch query item.
 * The backend retrieves from all `docIds` together and returns one synthesized
 * answer with citations from every contributing document.
 */
export async function sendSynthesizedBatchMessage(
  question: string,
  docIds: string[],
  options: ChatCallOptions = {}
): Promise<BatchChatResponse> {
  const matchCount = clampMatchCount(options.matchCount ?? DEFAULT_MATCH_COUNT);
  const scope = options.scope ?? "session";

  return postBatchChat(
    {
      scope,
      queries: [
        {
          question,
          doc_ids: docIds,
          match_count: matchCount,
        },
      ],
    },
    options.sessionId
  );
}

async function postBatchChat(
  body: Record<string, unknown>,
  sessionIdOverride?: string | null
): Promise<BatchChatResponse> {
  const sessionId =
    sessionIdOverride !== undefined ? sessionIdOverride : getSessionId();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...authHeaders(),
  };
  if (sessionId !== null) {
    headers["X-Session-Id"] = sessionId;
  }

  const requestBody: Record<string, unknown> = { ...body };
  if (sessionId !== null) {
    requestBody.session_id = sessionId;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/chat/batch`, {
      method: "POST",
      headers,
      body: JSON.stringify(requestBody),
    });
  } catch {
    throw new ChatError(
      "backend_unreachable",
      "Cannot reach the server. Check your connection."
    );
  }

  if (!res.ok) {
    await throwChatHttpError(res);
  }

  return (await res.json()) as BatchChatResponse;
}

export async function uploadDocument(
  file: File
): Promise<{ documentId: string; statusEndpoint: string; queuePosition?: number }> {
  const sessionId = getSessionId();
  const formData = new FormData();
  formData.append("file", file);
  
  const headers: Record<string, string> = { ...authHeaders() };
  if (sessionId !== null) {
    headers["X-Session-Id"] = sessionId;
  }

  const res = await fetch(`${API_BASE}/upload`, {
    method: "POST",
    headers,
    body: formData,
  });
  
  if (!res.ok) {
    throw await backendApiErrorFromResponse(
      res,
      res.status === 429 ? RATE_LIMITED_MESSAGE : "Upload failed. Please try again."
    );
  }
  const data = await res.json();
  const documentId = data?.document_id as string | undefined;
  const statusEndpoint = data?.status_endpoint as string | undefined;
  const queuePosition =
    typeof data?.queue_position === "number" ? data.queue_position : undefined;
  if (!documentId || !statusEndpoint) {
    throw new Error("Invalid upload response from server.");
  }
  return { documentId, statusEndpoint, queuePosition };
}

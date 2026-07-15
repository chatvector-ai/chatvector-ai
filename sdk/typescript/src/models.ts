/** The retrieval boundary used by chat and batch-chat requests. */
export type RetrievalScope = "session" | "tenant";

export type RequestOptions = {
  signal?: AbortSignal;
};

export type WaitForReadyOptions = RequestOptions & {
  timeoutMs?: number;
  pollIntervalMs?: number;
};

export type UploadInput =
  | { path: string; contentType?: string }
  | {
      data: Uint8Array | Blob;
      fileName: string;
      contentType?: string;
    };

export type ChatRequest = {
  question: string;
  docId: string;
  matchCount?: number;
  sessionId?: string;
  scope?: RetrievalScope;
};

export type BatchChatQuery = {
  question: string;
  docIds: string[];
  matchCount?: number;
  sessionId?: string;
  scope?: RetrievalScope;
};

export type BatchChatRequest = {
  queries: BatchChatQuery[];
  sessionId?: string;
  scope?: RetrievalScope;
};

export type ChatSource = {
  fileName: string | null;
  pageNumber: number | null;
  chunkIndex: number | null;
  score?: number | null;
  scoreType?: string | null;
};

export type DocumentResponse = {
  documentId: string;
  status: string;
  message?: string;
  queuePosition?: number;
  statusEndpoint?: string;
  _raw?: Record<string, unknown>;
};

export type DocumentStatus = {
  documentId: string;
  status: string;
  chunks?: Record<string, unknown> | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  error?: Record<string, unknown> | null;
  queuePosition?: number;
  _raw?: Record<string, unknown>;
};

export type ChatResponse = {
  question: string;
  docId: string;
  chunks: number;
  answer: string;
  sources: ChatSource[];
  latencyMs: number;
  model: string;
  status: "ok" | "error";
  error?: { code: string; message: string };
  _raw?: Record<string, unknown>;
};

export type BatchChatResult = {
  status: "ok" | "error";
  question: string;
  docIds: string[];
  chunks: number;
  answer?: string;
  sources?: ChatSource[];
  error?: { code: string; message: string };
  latencyMs: number;
  model: string;
  _raw?: Record<string, unknown>;
};

export type BatchChatResponse = {
  count: number;
  successCount: number;
  failureCount: number;
  results: BatchChatResult[];
  _raw?: Record<string, unknown>;
};

export type Session = {
  id: string;
  tenantId: string | null;
  createdAt: string;
  lastActive: string;
  metadata: Record<string, unknown>;
  documentIds: string[];
  _raw?: Record<string, unknown>;
};

export type SessionListResponse = {
  sessions: Session[];
  _raw?: Record<string, unknown>;
};

export type CreateSessionInput = { sessionId?: string };

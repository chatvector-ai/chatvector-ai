import type { ChatVectorAPIError } from "./errors.js";

/** The retrieval boundary used by chat and batch-chat requests. */
export type RetrievalScope = "session" | "tenant";

export type QueryTransformationStrategy =
  | "rewrite"
  | "expand"
  | "stepback"
  | "none";

export type RerankerProvider = "similarity" | "cohere";

/** Per-request retrieval overrides (nested ``retrieval`` on chat bodies). */
export type RetrievalConfig = {
  matchCount?: number;
  scope?: RetrievalScope;
  hybridEnabled?: boolean;
  rerankingEnabled?: boolean;
  rerankerProvider?: RerankerProvider;
  queryTransformationEnabled?: boolean;
  queryTransformationStrategy?: QueryTransformationStrategy;
  skipHistoryTransform?: boolean;
  /** Reserved for Named Retrieval Configuration Presets when backend ships it. */
  preset?: string;
  /** Document metadata filter; serialized as backend ``metadata_filter``. */
  metadataFilter?: Record<string, unknown>;
};

/** Per-request history overrides (nested ``history`` on chat bodies). */
export type HistoryConfig = {
  retrievalHistoryWindow?: number;
  generationHistoryWindow?: number;
  historyAwareRetrieval?: boolean;
  maxGenerationHistoryChars?: number;
};

export type RequestOptions = {
  signal?: AbortSignal;
};

export type WaitForReadyOptions = RequestOptions & {
  timeoutMs?: number;
  pollIntervalMs?: number;
};

export type UploadInput =
  | {
      path: string;
      contentType?: string;
      sessionId?: string;
      /** Re-ingest this completed/failed document in place instead of creating a new one. */
      replaceDocumentId?: string;
      idempotencyKey?: string;
      /** Document metadata sent as the multipart JSON ``metadata`` field. */
      metadata?: Record<string, unknown>;
    }
  | {
      data: Uint8Array | Blob;
      fileName: string;
      contentType?: string;
      sessionId?: string;
      /** Re-ingest this completed/failed document in place instead of creating a new one. */
      replaceDocumentId?: string;
      idempotencyKey?: string;
      /** Document metadata sent as the multipart JSON ``metadata`` field. */
      metadata?: Record<string, unknown>;
    };

/** Opt-in retrieval debug metadata when the backend exposes it. */
export type RetrievalDebugMetadata = {
  originalQuery?: string;
  transformedQueries?: string[];
  transformationStrategy?: string;
  effectiveRetrievalQuery?: string;
  timingMs?: Record<string, number>;
  effectiveConfig?: Record<string, unknown>;
  [key: string]: unknown;
};

export type ChatRequest = {
  question: string;
  docId: string;
  matchCount?: number;
  sessionId?: string;
  scope?: RetrievalScope;
  debugRetrieval?: boolean;
  retrieval?: RetrievalConfig;
  history?: HistoryConfig;
};

export type BatchChatQuery = {
  question: string;
  docIds: string[];
  matchCount?: number;
  sessionId?: string;
  scope?: RetrievalScope;
  retrieval?: RetrievalConfig;
  history?: HistoryConfig;
};

export type BatchChatRequest = {
  queries: BatchChatQuery[];
  sessionId?: string;
  scope?: RetrievalScope;
  debugRetrieval?: boolean;
  retrieval?: RetrievalConfig;
  history?: HistoryConfig;
};

export type ChatSource = {
  fileName: string | null;
  pageNumber: number | null;
  chunkIndex: number | null;
  score?: number | null;
  scoreType?: string | null;
  vectorScore?: number | null;
  fullTextScore?: number | null;
  rrfScore?: number | null;
  rerankerScore?: number | null;
  rerankOrder?: number | null;
};

export type DocumentSummary = {
  documentId: string;
  fileName: string | null;
  status: string;
  /** Set while a replacement is running or after one failed; never gates retrieval. */
  statusDetail?: string;
  createdAt?: string | null;
  updatedAt?: string | null;
  _raw?: Record<string, unknown>;
};

export type DocumentListResponse = {
  tenantId: string;
  documents: DocumentSummary[];
  _raw?: Record<string, unknown>;
};

export type SessionHistoryMessage = {
  id: string;
  role: string;
  content: string;
  createdAt?: string | null;
  /** Answer-time citation snapshot. ``null``/omitted is a pre-snapshot row. */
  sources?: Record<string, unknown>[] | null;
  _raw?: Record<string, unknown>;
};

export type SessionHistoryResponse = {
  messages: SessionHistoryMessage[];
  _raw?: Record<string, unknown>;
};

export type DocumentResponse = {
  documentId: string;
  status: string;
  message?: string;
  queuePosition?: number;
  statusEndpoint?: string;
  /** `"replacement_in_progress"` after a successful `replaceDocumentId` upload. */
  statusDetail?: string;
  _raw?: Record<string, unknown>;
};

export type BulkUploadResult = {
  path: string;
  success: boolean;
  document?: DocumentResponse;
  error?: ChatVectorAPIError;
};

export type BulkUploadSummary = {
  count: number;
  successCount: number;
  failureCount: number;
  results: BulkUploadResult[];
};

export type UploadManyOptions = RequestOptions & {
  concurrency?: number;
  sessionId?: string;
  failFast?: boolean;
  retryOnRateLimit?: boolean;
  maxRateLimitRetries?: number;
  idempotencyKeyForPath?: (path: string) => string | undefined;
  onProgress?: (result: BulkUploadResult, summary: BulkUploadSummary) => void;
  waitForReady?: boolean;
  waitForReadyTimeoutMs?: number;
  waitForReadyPollIntervalMs?: number;
};

export type UploadDirectoryOptions = UploadManyOptions & {
  pattern?: string;
  recursive?: boolean;
};

export type DocumentStatus = {
  documentId: string;
  status: string;
  chunks?: Record<string, unknown> | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  error?: Record<string, unknown> | null;
  queuePosition?: number;
  /**
   * `"replacement_in_progress"` while new content is being prepared (the prior
   * content stays retrievable) or `"replacement_failed"` after a failed attempt.
   */
  statusDetail?: string;
  /** Optional ingestion timing, attempt count, and failure classification. */
  job?: Record<string, unknown> | null;
  /** Document metadata when the status payload includes it. */
  metadata?: Record<string, unknown>;
  /** Document file name when the status payload includes it. */
  fileName?: string | null;
  _raw?: Record<string, unknown>;
};

export type ChatStreamEvent =
  | { type: "token"; content: string }
  | {
      type: "complete";
      sessionId: string | null;
      sources: ChatSource[];
      latencyMs: number;
      model: string;
      retrievalDebug?: RetrievalDebugMetadata;
      /**
       * Persisted assistant message id. Omitted when the server did not store
       * the turn. Absence is not an error.
       */
      messageId?: string;
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
  sessionId?: string | null;
  retrievalDebug?: RetrievalDebugMetadata;
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
  sessionId?: string | null;
  retrievalDebug?: RetrievalDebugMetadata;
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
  displayLabel: string;
  _raw?: Record<string, unknown>;
};

export type SessionListResponse = {
  sessions: Session[];
  _raw?: Record<string, unknown>;
};

export type CreateSessionInput = {
  sessionId?: string;
  idempotencyKey?: string;
};

export type FeedbackType = "answer" | "citation" | "retrieval";

export type PostFeedbackInput = {
  type: FeedbackType;
  rating: -1 | 1;
  sessionId: string;
  comment?: string;
  messageId?: string;
  documentId?: string;
  chunkIndex?: number;
};

export type ListFeedbackInput = {
  sessionId?: string;
  createdAfter?: string;
  createdBefore?: string;
  limit?: number;
};

export type FeedbackItem = {
  id: string;
  type: FeedbackType;
  rating: number;
  sessionId: string;
  createdAt: string;
  comment?: string | null;
  messageId?: string | null;
  documentId?: string | null;
  chunkIndex?: number | null;
  _raw?: Record<string, unknown>;
};

export type FeedbackListResponse = {
  feedback: FeedbackItem[];
  _raw?: Record<string, unknown>;
};

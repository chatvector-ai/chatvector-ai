import type { RetryOptions } from "./internal/retry.js";
import { HttpClient, type HttpClientOptions } from "./internal/http.js";
import type { Clock } from "./internal/time.js";
import type {
  BatchChatRequest,
  BatchChatResponse,
  ChatRequest,
  ChatResponse,
  ChatStreamEvent,
  CreateSessionInput,
  BulkUploadSummary,
  DocumentListResponse,
  DocumentResponse,
  DocumentStatus,
  RequestOptions,
  Session,
  SessionHistoryResponse,
  SessionListResponse,
  RetrievalPresetDiscoveryResponse,
  FeedbackItem,
  FeedbackListResponse,
  ListFeedbackInput,
  PostFeedbackInput,
  UploadDirectoryOptions,
  UploadInput,
  UploadManyOptions,
  WaitForReadyOptions,
} from "./models.js";
import type { UploadManyItem } from "./internal/bulk-upload.js";
import { ChatsResource } from "./resources/chats.js";
import { DocumentsResource } from "./resources/documents.js";
import { SessionsResource } from "./resources/sessions.js";
import { FeedbackResource } from "./resources/feedback.js";
import { RetrievalResource } from "./resources/retrieval.js";

export type ChatVectorClientOptions = {
  baseUrl: string;
  apiKey?: string;
  timeoutMs?: number;
  retry?: RetryOptions | false;
  fetch?: typeof globalThis.fetch;
};

type InternalClientOptions = ChatVectorClientOptions & {
  /** @internal Test seam, intentionally absent from the public option type. */
  __clock?: Clock;
  /** @internal Test seam, intentionally absent from the public option type. */
  __random?: () => number;
};

export class ChatVectorClient {
  private readonly documents: DocumentsResource;
  private readonly chats: ChatsResource;
  private readonly sessions: SessionsResource;
  private readonly feedback: FeedbackResource;
  private readonly retrieval: RetrievalResource;

  constructor(options: ChatVectorClientOptions) {
    if (!options || typeof options !== "object") {
      throw new TypeError("ChatVectorClient options are required");
    }
    const internal = options as InternalClientOptions;
    const httpOptions: HttpClientOptions = { baseUrl: options.baseUrl };
    if (options.apiKey !== undefined) httpOptions.apiKey = options.apiKey;
    if (options.timeoutMs !== undefined) httpOptions.timeoutMs = options.timeoutMs;
    if (options.retry !== undefined) httpOptions.retry = options.retry;
    if (options.fetch !== undefined) httpOptions.fetch = options.fetch;
    if (internal.__clock !== undefined) httpOptions.clock = internal.__clock;
    if (internal.__random !== undefined) httpOptions.random = internal.__random;

    const http = new HttpClient(httpOptions);
    this.documents = new DocumentsResource(http, internal.__clock);
    this.chats = new ChatsResource(http);
    this.sessions = new SessionsResource(http);
    this.feedback = new FeedbackResource(http);
    this.retrieval = new RetrievalResource(http);
  }

  uploadDocument(
    input: UploadInput,
    options?: RequestOptions,
  ): Promise<DocumentResponse> {
    return this.documents.uploadDocument(input, options);
  }

  uploadMany(
    items: readonly UploadManyItem[],
    options?: UploadManyOptions,
  ): Promise<BulkUploadSummary> {
    return this.documents.uploadMany(items, options ?? {});
  }

  uploadDirectory(
    directoryPath: string,
    options?: UploadDirectoryOptions,
  ): Promise<BulkUploadSummary> {
    return this.documents.uploadDirectory(directoryPath, options ?? {});
  }

  getDocumentStatus(
    documentId: string,
    options?: RequestOptions,
  ): Promise<DocumentStatus> {
    return this.documents.getDocumentStatus(documentId, options);
  }

  waitForReady(
    documentId: string,
    options?: WaitForReadyOptions,
  ): Promise<DocumentStatus> {
    return this.documents.waitForReady(documentId, options);
  }

  listDocuments(options?: RequestOptions): Promise<DocumentListResponse> {
    return this.documents.listDocuments(options);
  }

  listRetrievalPresets(
    options?: RequestOptions,
  ): Promise<RetrievalPresetDiscoveryResponse> {
    return this.retrieval.listRetrievalPresets(options);
  }

  deleteDocument(documentId: string, options?: RequestOptions): Promise<void> {
    return this.documents.deleteDocument(documentId, options);
  }

  streamDocumentStatus(
    documentId: string,
    options?: RequestOptions,
  ): AsyncIterable<DocumentStatus> {
    return this.documents.streamDocumentStatus(documentId, options);
  }

  chat(request: ChatRequest, options?: RequestOptions): Promise<ChatResponse> {
    return this.chats.chat(request, options);
  }

  streamChat(
    request: ChatRequest,
    options?: RequestOptions,
  ): AsyncIterable<ChatStreamEvent> {
    return this.chats.streamChat(request, options);
  }

  batchChat(
    request: BatchChatRequest,
    options?: RequestOptions,
  ): Promise<BatchChatResponse> {
    return this.chats.batchChat(request, options);
  }

  createSession(
    input?: CreateSessionInput,
    options?: RequestOptions,
  ): Promise<Session> {
    return this.sessions.createSession(input, options);
  }

  getSession(sessionId: string, options?: RequestOptions): Promise<Session> {
    return this.sessions.getSession(sessionId, options);
  }

  listSessions(options?: RequestOptions): Promise<SessionListResponse> {
    return this.sessions.listSessions(options);
  }

  deleteSession(sessionId: string, options?: RequestOptions): Promise<void> {
    return this.sessions.deleteSession(sessionId, options);
  }

  getSessionHistory(
    sessionId: string,
    options?: RequestOptions,
  ): Promise<SessionHistoryResponse> {
    return this.sessions.getSessionHistory(sessionId, options);
  }

  postFeedback(
    input: PostFeedbackInput,
    options?: RequestOptions,
  ): Promise<FeedbackItem> {
    return this.feedback.postFeedback(input, options);
  }

  listFeedback(
    input?: ListFeedbackInput,
    options?: RequestOptions,
  ): Promise<FeedbackListResponse> {
    return this.feedback.listFeedback(input ?? {}, options);
  }
}

import type { RetryOptions } from "./internal/retry.js";
import { HttpClient, type HttpClientOptions } from "./internal/http.js";
import type { Clock } from "./internal/time.js";
import type {
  BatchChatRequest,
  BatchChatResponse,
  ChatRequest,
  ChatResponse,
  CreateSessionInput,
  DocumentResponse,
  DocumentStatus,
  RequestOptions,
  Session,
  SessionListResponse,
  UploadInput,
  WaitForReadyOptions,
} from "./models.js";
import { ChatsResource } from "./resources/chats.js";
import { DocumentsResource } from "./resources/documents.js";
import { SessionsResource } from "./resources/sessions.js";

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
  }

  uploadDocument(
    input: UploadInput,
    options?: RequestOptions,
  ): Promise<DocumentResponse> {
    return this.documents.uploadDocument(input, options);
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

  chat(request: ChatRequest, options?: RequestOptions): Promise<ChatResponse> {
    return this.chats.chat(request, options);
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
}

import type {
  CreateSessionInput,
  RequestOptions,
  Session,
  SessionHistoryMessage,
  SessionHistoryResponse,
  SessionListResponse,
} from "../models.js";
import { HttpClient } from "../internal/http.js";
import { isRecord, signalOption, stringValue } from "../internal/utils.js";

export class SessionsResource {
  constructor(private readonly http: HttpClient) {}

  async createSession(
    input: CreateSessionInput = {},
    options: RequestOptions = {},
  ): Promise<Session> {
    const body: Record<string, unknown> = {};
    if (input.sessionId !== undefined) body.session_id = input.sessionId;
    const headers: Record<string, string> = {};
    const idempotencyKey = input.idempotencyKey?.trim();
    if (idempotencyKey) {
      headers["Idempotency-Key"] = idempotencyKey;
    }
    const payload = await this.http.requestJson("POST", "/sessions", {
      json: body,
      ...(Object.keys(headers).length > 0 ? { headers } : {}),
      ...signalOption(options.signal),
    });
    return mapSession(payload);
  }

  async getSession(
    sessionId: string,
    options: RequestOptions = {},
  ): Promise<Session> {
    assertSessionId(sessionId);
    const payload = await this.http.requestJson(
      "GET",
      `/sessions/${encodeURIComponent(sessionId)}`,
      signalOption(options.signal),
    );
    return mapSession(payload);
  }

  async listSessions(
    options: RequestOptions = {},
  ): Promise<SessionListResponse> {
    const payload = await this.http.requestJson(
      "GET",
      "/sessions",
      signalOption(options.signal),
    );
    return {
      sessions: Array.isArray(payload.sessions)
        ? payload.sessions.filter(isRecord).map(mapSession)
        : [],
      _raw: payload,
    };
  }

  async deleteSession(
    sessionId: string,
    options: RequestOptions = {},
  ): Promise<void> {
    assertSessionId(sessionId);
    await this.http.requestVoid(
      "DELETE",
      `/sessions/${encodeURIComponent(sessionId)}`,
      signalOption(options.signal),
    );
  }

  async getSessionHistory(
    sessionId: string,
    options: RequestOptions = {},
  ): Promise<SessionHistoryResponse> {
    assertSessionId(sessionId);
    const payload = await this.http.requestJson(
      "GET",
      `/sessions/${encodeURIComponent(sessionId)}/history`,
      signalOption(options.signal),
    );
    const messages = Array.isArray(payload.messages)
      ? payload.messages.filter(isRecord).map(mapSessionHistoryMessage)
      : [];
    return { messages, _raw: payload };
  }
}

function mapSession(payload: Record<string, unknown>): Session {
  const label = payload.display_label;
  return {
    id: stringValue(payload.id),
    tenantId: typeof payload.tenant_id === "string" ? payload.tenant_id : null,
    createdAt: stringValue(payload.created_at),
    lastActive: stringValue(payload.last_active),
    metadata: isRecord(payload.metadata) ? payload.metadata : {},
    documentIds: Array.isArray(payload.document_ids)
      ? payload.document_ids.filter(
          (item): item is string => typeof item === "string",
        )
      : [],
    displayLabel: typeof label === "string" && label.length > 0 ? label : "New session",
    _raw: payload,
  };
}

function mapSessionHistoryMessage(
  payload: Record<string, unknown>,
): SessionHistoryMessage {
  const result: SessionHistoryMessage = {
    id: stringValue(payload.id),
    role: stringValue(payload.role),
    content: stringValue(payload.content),
    _raw: payload,
  };
  if (payload.created_at === null || typeof payload.created_at === "string") {
    result.createdAt = payload.created_at;
  }
  if (payload.sources === null) {
    result.sources = null;
  } else if (Array.isArray(payload.sources)) {
    result.sources = payload.sources.filter(isRecord);
  }
  return result;
}

function assertSessionId(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError("sessionId must be a non-empty string");
  }
}

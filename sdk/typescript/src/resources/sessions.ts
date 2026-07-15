import type {
  CreateSessionInput,
  RequestOptions,
  Session,
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
    const payload = await this.http.requestJson("POST", "/sessions", {
      json: body,
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
}

function mapSession(payload: Record<string, unknown>): Session {
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
    _raw: payload,
  };
}

function assertSessionId(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError("sessionId must be a non-empty string");
  }
}

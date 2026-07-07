import { API_BASE, authHeaders } from "./api";

export type ComponentHealth = {
  status: "ok" | "error";
  latency_ms?: number;
  error?: string;
  cached?: boolean;
  checked_at?: string;
};

export type SystemStatus = {
  status: "healthy" | "degraded" | "unhealthy";
  components: {
    api: string;
    database: string;
    queue: string;
    embeddings: string;
    llm: string;
  };
  health_checks: {
    embedding: ComponentHealth;
    llm: ComponentHealth;
    redis?: ComponentHealth;
  };
  metrics: {
    document_queue: number;
    workers_active: number;
    memory_usage: number;
    documents_indexed: number | null;
    total_queries: number | null;
  };
  uptime: string;
  version: string;
};

export type StatusFetchErrorKind =
  | "network"
  | "unexpected_response"
  | "invalid_json"
  | "http_error";

export class StatusFetchError extends Error {
  readonly kind: StatusFetchErrorKind;
  readonly httpStatus?: number;
  readonly contentType?: string;

  constructor(
    message: string,
    kind: StatusFetchErrorKind,
    options?: { httpStatus?: number; contentType?: string }
  ) {
    super(message);
    this.name = "StatusFetchError";
    this.kind = kind;
    this.httpStatus = options?.httpStatus;
    this.contentType = options?.contentType;
  }
}

function mediaType(contentType: string | null): string {
  if (!contentType) return "unknown";
  return contentType.split(";")[0]?.trim().toLowerCase() || "unknown";
}

function isJsonMediaType(contentType: string | null): boolean {
  const type = mediaType(contentType);
  return type === "application/json" || type.endsWith("+json");
}

function looksLikeHtml(contentType: string | null, body: string): boolean {
  if (mediaType(contentType) === "text/html") return true;
  const trimmed = body.trimStart();
  return trimmed.startsWith("<") || trimmed.startsWith("<!");
}

function formatHttpDetail(httpStatus: number, contentType: string | null): string {
  return `HTTP ${httpStatus} · Expected JSON but received ${mediaType(contentType)}.`;
}

function unexpectedResponseDetail(
  httpStatus: number,
  contentType: string | null,
  body: string
): string {
  if (looksLikeHtml(contentType, body)) {
    return `HTTP ${httpStatus} · Expected JSON but received text/html.`;
  }
  return formatHttpDetail(httpStatus, contentType);
}

export function statusErrorTitle(kind: StatusFetchErrorKind): string {
  switch (kind) {
    case "network":
      return "Backend Unreachable";
    case "unexpected_response":
      return "Unexpected Response";
    case "invalid_json":
      return "Unreadable Response";
    case "http_error":
      return "Backend Error";
  }
}

function parseSystemStatus(parsed: unknown): SystemStatus {
  if (parsed == null || typeof parsed !== "object") {
    throw new StatusFetchError(
      "The backend response could not be read.\n\nThe payload did not look like a system status response.",
      "invalid_json"
    );
  }

  const payload = parsed as Record<string, unknown>;
  const status = payload.status;
  if (status !== "healthy" && status !== "degraded" && status !== "unhealthy") {
    throw new StatusFetchError(
      "The backend response could not be read.\n\nThe payload did not look like a system status response.",
      "invalid_json"
    );
  }

  if (payload.components == null || typeof payload.components !== "object") {
    throw new StatusFetchError(
      "The backend response could not be read.\n\nThe payload did not look like a system status response.",
      "invalid_json"
    );
  }

  if (payload.metrics == null || typeof payload.metrics !== "object") {
    throw new StatusFetchError(
      "The backend response could not be read.\n\nThe payload did not look like a system status response.",
      "invalid_json"
    );
  }

  if (typeof payload.uptime !== "string" || typeof payload.version !== "string") {
    throw new StatusFetchError(
      "The backend response could not be read.\n\nThe payload did not look like a system status response.",
      "invalid_json"
    );
  }

  return parsed as SystemStatus;
}

export async function getSystemStatus(): Promise<SystemStatus> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/status`, {
      method: "GET",
      headers: {
        Accept: "application/json",
        ...authHeaders(),
      },
      cache: "no-store",
    });
  } catch (err) {
    if (process.env.NODE_ENV === "development") {
      console.error("[status] Network request failed:", err);
    }
    throw new StatusFetchError(
      "Unable to connect to the ChatVector backend.\n\nCheck that the backend is running and the API URL is configured correctly.",
      "network"
    );
  }

  const contentType = res.headers.get("content-type");
  const body = await res.text();

  if (!body.trim()) {
    if (process.env.NODE_ENV === "development") {
      console.error("[status] Empty response body:", {
        status: res.status,
        contentType,
      });
    }
    throw new StatusFetchError(
      `The backend returned an empty response.\n\nHTTP ${res.status} · No response body.`,
      "unexpected_response",
      { httpStatus: res.status, contentType: contentType ?? undefined }
    );
  }

  if (looksLikeHtml(contentType, body)) {
    if (process.env.NODE_ENV === "development") {
      console.error("[status] Unexpected HTML response:", {
        status: res.status,
        contentType,
        bodyPreview: body.slice(0, 200),
      });
    }
    throw new StatusFetchError(
      `The backend returned an unexpected response.\n\n${unexpectedResponseDetail(res.status, contentType, body)}`,
      "unexpected_response",
      { httpStatus: res.status, contentType: contentType ?? undefined }
    );
  }

  if (!isJsonMediaType(contentType)) {
    if (process.env.NODE_ENV === "development") {
      console.error("[status] Unexpected non-JSON response:", {
        status: res.status,
        contentType,
        bodyPreview: body.slice(0, 200),
      });
    }
    throw new StatusFetchError(
      `The backend returned an unexpected response.\n\n${formatHttpDetail(res.status, contentType)}`,
      "unexpected_response",
      { httpStatus: res.status, contentType: contentType ?? undefined }
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch (err) {
    if (process.env.NODE_ENV === "development") {
      console.error("[status] Invalid JSON response:", {
        status: res.status,
        contentType,
        err,
        bodyPreview: body.slice(0, 200),
      });
    }
    throw new StatusFetchError(
      `The backend response could not be read.\n\nHTTP ${res.status} · The response was not valid JSON.`,
      "invalid_json",
      { httpStatus: res.status, contentType: contentType ?? undefined }
    );
  }

  if (!res.ok) {
    if (process.env.NODE_ENV === "development") {
      console.error("[status] Non-success HTTP status with JSON body:", {
        status: res.status,
        contentType,
        body: parsed,
      });
    }
    throw new StatusFetchError(
      `The backend returned an error response.\n\nHTTP ${res.status} · ${res.statusText || "Request failed"}.`,
      "http_error",
      { httpStatus: res.status, contentType: contentType ?? undefined }
    );
  }

  return parseSystemStatus(parsed);
}

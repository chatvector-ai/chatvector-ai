export type ChatVectorErrorKind =
  | "api"
  | "auth"
  | "rate_limit"
  | "timeout";

type ChatVectorAPIErrorOptions = {
  statusCode?: number;
  code?: string;
  details?: unknown;
  cause?: unknown;
};

type ChatVectorRateLimitErrorOptions = ChatVectorAPIErrorOptions & {
  retryAfterMs?: number;
};

/** Base class for errors returned by, or raised while calling, ChatVector. */
export class ChatVectorAPIError extends Error {
  readonly kind: ChatVectorErrorKind = "api";
  readonly statusCode?: number;
  readonly code?: string;
  readonly details?: unknown;
  override readonly cause?: unknown;

  constructor(message: string, options: ChatVectorAPIErrorOptions = {}) {
    super(message);
    this.name = "ChatVectorAPIError";
    if (options.statusCode !== undefined) {
      this.statusCode = options.statusCode;
    }
    if (options.code !== undefined) {
      this.code = options.code;
    }
    this.details = options.details;
    this.cause = options.cause;
  }
}

/** An authentication or authorization failure (HTTP 401 or 403). */
export class ChatVectorAuthError extends ChatVectorAPIError {
  override readonly kind = "auth" as const;

  constructor(message: string, options: ChatVectorAPIErrorOptions = {}) {
    super(message, options);
    this.name = "ChatVectorAuthError";
  }
}

/** A server rate-limit response (HTTP 429). */
export class ChatVectorRateLimitError extends ChatVectorAPIError {
  override readonly kind = "rate_limit" as const;
  readonly retryAfterMs?: number;

  constructor(
    message: string,
    options: ChatVectorRateLimitErrorOptions = {},
  ) {
    super(message, options);
    this.name = "ChatVectorRateLimitError";
    if (options.retryAfterMs !== undefined) {
      this.retryAfterMs = options.retryAfterMs;
    }
  }
}

/** A request, polling deadline, or retryable transport timeout. */
export class ChatVectorTimeoutError extends ChatVectorAPIError {
  override readonly kind = "timeout" as const;

  constructor(message: string, options: ChatVectorAPIErrorOptions = {}) {
    super(message, options);
    this.name = "ChatVectorTimeoutError";
  }
}

const CHATVECTOR_ERROR_KINDS: ReadonlySet<ChatVectorErrorKind> = new Set([
  "api",
  "auth",
  "rate_limit",
  "timeout",
]);

/**
 * Recognizes SDK errors structurally so duplicate ESM/CJS package instances do
 * not make error handling depend on `instanceof` identity.
 */
export function isChatVectorError(
  error: unknown,
): error is ChatVectorAPIError {
  if (
    (typeof error !== "object" && typeof error !== "function") ||
    error === null
  ) {
    return false;
  }

  try {
    const candidate = error as { kind?: unknown; message?: unknown };
    return (
      typeof candidate.kind === "string" &&
      CHATVECTOR_ERROR_KINDS.has(candidate.kind as ChatVectorErrorKind) &&
      typeof candidate.message === "string"
    );
  } catch {
    return false;
  }
}

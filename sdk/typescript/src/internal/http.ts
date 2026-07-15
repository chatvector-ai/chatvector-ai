import {
  ChatVectorAPIError,
  ChatVectorAuthError,
  ChatVectorRateLimitError,
  ChatVectorTimeoutError,
  isChatVectorError,
} from "../errors.js";
import {
  calculateRetryDelayMs,
  isRetryableMethod,
  isRetryableStatus,
  parseRetryAfter,
  resolveRetryOptions,
  type RandomSource,
  type ResolvedRetryOptions,
  type RetryOptions,
} from "./retry.js";
import {
  abortReason,
  systemClock,
  throwIfAborted,
  type Clock,
} from "./time.js";
import { isRecord } from "./utils.js";

const DEFAULT_TIMEOUT_MS = 30_000;

export type HttpClientOptions = {
  baseUrl: string;
  apiKey?: string;
  timeoutMs?: number;
  retry?: RetryOptions | false;
  fetch?: typeof globalThis.fetch;
  clock?: Clock;
  random?: RandomSource;
};

export type HttpRequestOptions = {
  signal?: AbortSignal;
  json?: unknown;
  body?: BodyInit;
  deadlineMs?: number;
};

class RequestDeadlineError extends Error {
  constructor() {
    super("The ChatVector request deadline expired.");
    this.name = "RequestDeadlineError";
  }
}

export class HttpClient {
  private readonly baseUrl: string;
  private readonly authHeader: string | undefined;
  private readonly timeoutMs: number;
  private readonly retry: ResolvedRetryOptions;
  private readonly fetchImplementation: typeof globalThis.fetch;
  private readonly clock: Clock;
  private readonly random: RandomSource;
  private readonly apiKey: string | undefined;

  constructor(options: HttpClientOptions) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl);
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    if (!Number.isFinite(this.timeoutMs) || this.timeoutMs <= 0) {
      throw new RangeError("timeoutMs must be a positive finite number");
    }

    if (options.apiKey !== undefined && typeof options.apiKey !== "string") {
      throw new TypeError("apiKey must be a string when provided");
    }

    const fetchImplementation = options.fetch ?? globalThis.fetch;
    if (typeof fetchImplementation !== "function") {
      throw new TypeError("A fetch implementation is required");
    }

    this.apiKey = options.apiKey || undefined;
    this.authHeader = this.apiKey
      ? `Bearer ${this.apiKey}`
      : undefined;
    this.retry = resolveRetryOptions(options.retry);
    this.fetchImplementation = fetchImplementation;
    this.clock = options.clock ?? systemClock;
    this.random = options.random ?? Math.random;
  }

  async requestJson(
    method: string,
    path: string,
    options: HttpRequestOptions = {},
  ): Promise<Record<string, unknown>> {
    const { response, text } = await this.request(method, path, options, true);
    let payload: unknown;

    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      throw new ChatVectorAPIError(
        "ChatVector returned a non-JSON response.",
        { statusCode: response.status },
      );
    }

    const sanitized = redactSecret(payload, this.apiKey);
    if (!isRecord(sanitized)) {
      throw new ChatVectorAPIError(
        "ChatVector returned an unexpected response shape.",
        { statusCode: response.status, details: sanitized },
      );
    }

    return sanitized;
  }

  async requestVoid(
    method: string,
    path: string,
    options: HttpRequestOptions = {},
  ): Promise<void> {
    await this.request(method, path, options, false);
  }

  private async request(
    method: string,
    path: string,
    options: HttpRequestOptions,
    readBody: boolean,
  ): Promise<{ response: Response; text: string }> {
    const normalizedMethod = method.toUpperCase();
    const url = `${this.baseUrl}/${path.replace(/^\/+/, "")}`;
    let retryIndex = 0;

    while (true) {
      throwIfAborted(options.signal);
      if (
        options.deadlineMs !== undefined &&
        this.clock.now() >= options.deadlineMs
      ) {
        throw new ChatVectorTimeoutError("The operation deadline expired.");
      }

      try {
        const response = await this.fetchOnce(normalizedMethod, url, options);
        if (response.ok) {
          const text = readBody
            ? await this.readResponseText(response, options.signal)
            : "";
          return { response, text };
        }

        const retryAfterMs = parseRetryAfter(
          response.headers.get("retry-after"),
          this.clock.now(),
        );
        if (
          isRetryableMethod(normalizedMethod) &&
          isRetryableStatus(response.status) &&
          retryIndex < this.retry.maxRetries
        ) {
          const delayMs = calculateRetryDelayMs(
            retryIndex,
            this.retry,
            retryAfterMs,
            this.random,
          );
          retryIndex += 1;
          discardBody(response);
          await this.clock.sleep(
            capToDeadline(delayMs, options.deadlineMs, this.clock.now()),
            options.signal,
          );
          continue;
        }

        const text = await this.readResponseText(response, options.signal);
        throw this.decodeHttpError(response, retryAfterMs, text);
      } catch (error) {
        if (options.signal?.aborted) {
          throw abortReason(options.signal);
        }
        if (isChatVectorError(error)) {
          throw error;
        }

        const transportError = this.mapTransportError(error);
        if (
          transportError.retryable &&
          isRetryableMethod(normalizedMethod) &&
          retryIndex < this.retry.maxRetries
        ) {
          const delayMs = calculateRetryDelayMs(
            retryIndex,
            this.retry,
            undefined,
            this.random,
          );
          retryIndex += 1;
          await this.clock.sleep(
            capToDeadline(delayMs, options.deadlineMs, this.clock.now()),
            options.signal,
          );
          continue;
        }

        throw transportError.error;
      }
    }
  }

  private async fetchOnce(
    method: string,
    url: string,
    options: HttpRequestOptions,
  ): Promise<Response> {
    throwIfAborted(options.signal);

    const controller = new AbortController();
    let deadlineExpired = false;
    const onAbort = (): void => {
      controller.abort(
        options.signal === undefined
          ? abortError()
          : abortReason(options.signal),
      );
    };

    options.signal?.addEventListener("abort", onAbort, { once: true });
    if (options.signal?.aborted) {
      onAbort();
    }

    const timer = setTimeout(() => {
      deadlineExpired = true;
      controller.abort(new DOMException("The request timed out", "TimeoutError"));
    }, this.timeoutMs);

    const headers = new Headers({ Accept: "application/json" });
    if (this.authHeader) {
      headers.set("Authorization", this.authHeader);
    }

    const init: RequestInit = {
      method,
      headers,
      signal: controller.signal,
    };

    if (Object.prototype.hasOwnProperty.call(options, "json")) {
      headers.set("Content-Type", "application/json");
      init.body = JSON.stringify(options.json);
    } else if (options.body !== undefined) {
      init.body = options.body;
    }

    try {
      return await this.fetchImplementation(url, init);
    } catch (error) {
      if (options.signal?.aborted) {
        throw abortReason(options.signal);
      }
      if (deadlineExpired) {
        throw new RequestDeadlineError();
      }
      throw error;
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }
  }

  private async readResponseText(
    response: Response,
    signal?: AbortSignal,
  ): Promise<string> {
    throwIfAborted(signal);
    if (response.body === null) {
      return "";
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const chunks: string[] = [];
    let deadlineExpired = false;
    let rejectInterruption: ((reason: unknown) => void) | undefined;
    const interruption = new Promise<never>((_resolve, reject) => {
      rejectInterruption = reject;
    });
    const onAbort = (): void => {
      rejectInterruption?.(
        signal === undefined ? abortError() : abortReason(signal),
      );
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    if (signal?.aborted) onAbort();
    const timer = setTimeout(() => {
      deadlineExpired = true;
      rejectInterruption?.(new RequestDeadlineError());
    }, this.timeoutMs);

    try {
      while (true) {
        const result = await Promise.race([reader.read(), interruption]);
        if (result.done) break;
        chunks.push(decoder.decode(result.value, { stream: true }));
      }
      chunks.push(decoder.decode());
      return chunks.join("");
    } catch (error) {
      try {
        void reader.cancel().catch(() => undefined);
      } catch {
        // The typed transport error below remains authoritative.
      }
      if (signal?.aborted) throw abortReason(signal);
      if (deadlineExpired) throw new RequestDeadlineError();
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }
  }

  private mapTransportError(error: unknown): {
    retryable: boolean;
    error: ChatVectorAPIError;
  } {
    if (isTimeoutOrConnectionError(error)) {
      return {
        retryable: true,
        error: new ChatVectorTimeoutError(
          "The ChatVector request timed out or could not connect.",
        ),
      };
    }

    return {
      retryable: false,
      error: new ChatVectorAPIError(
        "An unexpected transport error occurred while calling ChatVector.",
        { details: { error: safeErrorName(error) } },
      ),
    };
  }

  private decodeHttpError(
    response: Response,
    retryAfterMs: number | undefined,
    rawText: string,
  ): ChatVectorAPIError {
    let decoded: unknown;
    let hasDecodedBody = false;

    if (rawText.length > 0) {
      try {
        decoded = JSON.parse(rawText) as unknown;
        hasDecodedBody = true;
      } catch {
        decoded = undefined;
      }
    }

    const details = hasDecodedBody
      ? redactSecret(decoded, this.apiKey)
      : undefined;
    const extracted = extractError(details);
    const fallback = defaultErrorMessage(response.status);
    const message = redactText(
      extracted.message ??
        (hasDecodedBody ? fallback : rawText.trim() || fallback),
      this.apiKey,
    );
    const common = {
      statusCode: response.status,
      ...(extracted.code === undefined ? {} : { code: extracted.code }),
      ...(details === undefined ? {} : { details }),
    };

    if (response.status === 401 || response.status === 403) {
      return new ChatVectorAuthError(message, common);
    }
    if (response.status === 429) {
      return new ChatVectorRateLimitError(message, {
        ...common,
        ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
      });
    }
    if (response.status === 408 || response.status === 504) {
      return new ChatVectorTimeoutError(message, common);
    }
    return new ChatVectorAPIError(message, common);
  }
}

function normalizeBaseUrl(value: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError("baseUrl must be a non-empty absolute URL");
  }

  const normalized = value.trim().replace(/\/+$/, "");
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new TypeError("baseUrl must be a valid absolute URL");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new TypeError("baseUrl must use http or https");
  }
  if (parsed.search || parsed.hash) {
    throw new TypeError("baseUrl must not contain a query string or fragment");
  }

  return normalized;
}

function isTimeoutOrConnectionError(error: unknown): boolean {
  if (error instanceof RequestDeadlineError || error instanceof TypeError) {
    return true;
  }
  if (!isRecord(error)) {
    return false;
  }
  const name = error.name;
  const code = error.code;
  return (
    name === "TimeoutError" ||
    code === "ETIMEDOUT" ||
    code === "ECONNRESET" ||
    code === "ECONNREFUSED" ||
    code === "EAI_AGAIN" ||
    code === "ENOTFOUND"
  );
}

function safeErrorName(error: unknown): string {
  return isRecord(error) && typeof error.name === "string"
    ? error.name
    : "UnknownError";
}

function extractError(payload: unknown): {
  message?: string;
  code?: string;
} {
  if (!isRecord(payload)) {
    return {};
  }

  const detail = Object.prototype.hasOwnProperty.call(payload, "detail")
    ? payload.detail
    : payload;
  if (typeof detail === "string" && detail.length > 0) {
    return { message: detail };
  }
  if (!isRecord(detail)) {
    return {};
  }

  return {
    ...(typeof detail.message === "string" && detail.message.length > 0
      ? { message: detail.message }
      : {}),
    ...(typeof detail.code === "string" && detail.code.length > 0
      ? { code: detail.code }
      : {}),
  };
}

function defaultErrorMessage(statusCode: number): string {
  if (statusCode === 401 || statusCode === 403) {
    return "Authentication with ChatVector failed.";
  }
  if (statusCode === 429) {
    return "The ChatVector rate limit was exceeded.";
  }
  if (statusCode === 408 || statusCode === 504) {
    return "The ChatVector request timed out.";
  }
  return `ChatVector returned HTTP ${statusCode}.`;
}

function redactText(value: string, secret: string | undefined): string {
  return secret ? value.replaceAll(secret, "[REDACTED]") : value;
}

function redactSecret(value: unknown, secret: string | undefined): unknown {
  if (!secret) {
    return value;
  }
  if (typeof value === "string") {
    return redactText(value, secret);
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactSecret(item, secret));
  }
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        redactText(key, secret),
        redactSecret(item, secret),
      ]),
    );
  }
  return value;
}



function abortError(): DOMException {
  return new DOMException("The operation was aborted", "AbortError");
}

function discardBody(response: Response): void {
  try {
    void response.body?.cancel().catch(() => undefined);
  } catch {
    // A retry does not depend on whether the rejected response body can close.
  }
}

function capToDeadline(
  delayMs: number,
  deadlineMs: number | undefined,
  nowMs: number,
): number {
  return deadlineMs === undefined
    ? delayMs
    : Math.max(0, Math.min(delayMs, deadlineMs - nowMs));
}

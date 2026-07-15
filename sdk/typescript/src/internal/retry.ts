export type RetryOptions = {
  maxRetries?: number;
  initialDelayMs?: number;
  maxDelayMs?: number;
};

export type ResolvedRetryOptions = Readonly<Required<RetryOptions>>;

export type RandomSource = () => number;

export const DEFAULT_RETRY_OPTIONS: ResolvedRetryOptions = Object.freeze({
  maxRetries: 2,
  initialDelayMs: 500,
  maxDelayMs: 8_000,
});

export const RETRYABLE_STATUS_CODES: ReadonlySet<number> = new Set([
  408,
  429,
  502,
  503,
  504,
]);

function assertNonNegativeSafeInteger(value: number, name: string): void {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new RangeError(`${name} must be a non-negative safe integer`);
  }
}

function assertNonNegativeFinite(value: number, name: string): void {
  if (!Number.isFinite(value) || value < 0) {
    throw new RangeError(`${name} must be a non-negative finite number`);
  }
}

/** Applies retry defaults and validates options before any request is made. */
export function resolveRetryOptions(
  options: RetryOptions | false | undefined,
): ResolvedRetryOptions {
  if (options === false) {
    return { ...DEFAULT_RETRY_OPTIONS, maxRetries: 0 };
  }

  const resolved: ResolvedRetryOptions = {
    maxRetries: options?.maxRetries ?? DEFAULT_RETRY_OPTIONS.maxRetries,
    initialDelayMs:
      options?.initialDelayMs ?? DEFAULT_RETRY_OPTIONS.initialDelayMs,
    maxDelayMs: options?.maxDelayMs ?? DEFAULT_RETRY_OPTIONS.maxDelayMs,
  };

  assertNonNegativeSafeInteger(resolved.maxRetries, "maxRetries");
  assertNonNegativeFinite(resolved.initialDelayMs, "initialDelayMs");
  assertNonNegativeFinite(resolved.maxDelayMs, "maxDelayMs");

  return resolved;
}

/** Only safe, idempotent reads are automatically replayed in v0. */
export function isRetryableMethod(method: string): boolean {
  const normalized = method.toUpperCase();
  return normalized === "GET" || normalized === "HEAD";
}

export function isRetryableStatus(statusCode: number): boolean {
  return RETRYABLE_STATUS_CODES.has(statusCode);
}

/**
 * Parses either Retry-After delta-seconds or an HTTP date into milliseconds.
 * Invalid values and dates that have already expired are ignored.
 */
export function parseRetryAfter(
  value: string | null | undefined,
  nowMs = Date.now(),
): number | undefined {
  if (value === null || value === undefined) {
    return undefined;
  }

  const normalized = value.trim();
  if (normalized.length === 0) {
    return undefined;
  }

  if (/^\d+$/.test(normalized)) {
    const seconds = Number(normalized);
    const milliseconds = seconds * 1_000;
    return Number.isSafeInteger(milliseconds) ? milliseconds : undefined;
  }

  if (!Number.isFinite(nowMs)) {
    return undefined;
  }

  const retryAtMs = Date.parse(normalized);
  if (!Number.isFinite(retryAtMs) || retryAtMs <= nowMs) {
    return undefined;
  }

  return retryAtMs - nowMs;
}

/**
 * Computes bounded exponential full jitter. A valid Retry-After value acts as
 * a floor, even when that exceeds the configured jitter cap.
 */
export function calculateRetryDelayMs(
  retryIndex: number,
  options: ResolvedRetryOptions,
  retryAfterMs?: number,
  random: RandomSource = Math.random,
): number {
  assertNonNegativeSafeInteger(retryIndex, "retryIndex");
  assertNonNegativeFinite(options.initialDelayMs, "initialDelayMs");
  assertNonNegativeFinite(options.maxDelayMs, "maxDelayMs");

  const randomValue = random();
  if (!Number.isFinite(randomValue) || randomValue < 0 || randomValue > 1) {
    throw new RangeError("random must return a finite number between 0 and 1");
  }

  const exponentialDelay = options.initialDelayMs * 2 ** retryIndex;
  const jitterLimit = Math.min(exponentialDelay, options.maxDelayMs);
  const jitterDelay = Math.min(randomValue * jitterLimit, jitterLimit);

  if (retryAfterMs === undefined) {
    return jitterDelay;
  }

  assertNonNegativeFinite(retryAfterMs, "retryAfterMs");
  return Math.max(jitterDelay, retryAfterMs);
}

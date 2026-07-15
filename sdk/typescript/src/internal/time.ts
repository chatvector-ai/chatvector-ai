/** Injectable time boundary used by polling and retry tests. */
export interface Clock {
  now(): number;
  sleep(delayMs: number, signal?: AbortSignal): Promise<void>;
}

const MAX_TIMER_DELAY_MS = 2_147_483_647;

export function abortReason(signal: AbortSignal): unknown {
  return "reason" in signal
    ? signal.reason
    : new DOMException("The operation was aborted", "AbortError");
}

/** Throws the signal's original reason, preserving the platform AbortError. */
export function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) {
    throw abortReason(signal);
  }
}

/** An abort-aware sleep primitive. A zero delay still yields to the event loop. */
export function sleep(delayMs: number, signal?: AbortSignal): Promise<void> {
  if (!Number.isFinite(delayMs) || delayMs < 0) {
    return Promise.reject(
      new RangeError("delayMs must be a non-negative finite number"),
    );
  }

  try {
    throwIfAborted(signal);
  } catch (error) {
    return Promise.reject(error);
  }

  return sleepInChunks(delayMs, signal);
}

async function sleepInChunks(
  delayMs: number,
  signal?: AbortSignal,
): Promise<void> {
  let remainingMs = delayMs;
  do {
    const chunkMs = Math.min(remainingMs, MAX_TIMER_DELAY_MS);
    await sleepOnce(chunkMs, signal);
    remainingMs -= chunkMs;
  } while (remainingMs > 0);
}

function sleepOnce(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined;

    const cleanup = (): void => {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
      signal?.removeEventListener("abort", onAbort);
    };

    const onAbort = (): void => {
      cleanup();
      reject(abortReason(signal!));
    };

    timer = setTimeout(() => {
      cleanup();
      resolve();
    }, delayMs);

    signal?.addEventListener("abort", onAbort, { once: true });

    // Close the small race between the initial check and listener attachment.
    if (signal?.aborted) {
      onAbort();
    }
  });
}

export const systemClock: Clock = Object.freeze({
  now: () => Date.now(),
  sleep,
});

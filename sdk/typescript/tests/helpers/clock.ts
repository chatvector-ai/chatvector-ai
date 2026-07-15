import { vi } from "vitest";

import { abortReason, throwIfAborted, type Clock } from "../../src/internal/time.js";

export function createAdvancingClock(startMs = 0): {
  clock: Clock;
  sleeps: number[];
  sleepMock: ReturnType<typeof vi.fn<Clock["sleep"]>>;
  setNow(value: number): void;
} {
  let nowMs = startMs;
  const sleeps: number[] = [];
  const sleepMock = vi.fn<Clock["sleep"]>(
    async (delayMs: number, signal?: AbortSignal): Promise<void> => {
      throwIfAborted(signal);
      sleeps.push(delayMs);
      nowMs += delayMs;
    },
  );
  return {
    clock: { now: () => nowMs, sleep: sleepMock },
    sleeps,
    sleepMock,
    setNow(value: number): void {
      nowMs = value;
    },
  };
}

export function createBlockingClock(startMs = 0): {
  clock: Clock;
  sleepMock: ReturnType<typeof vi.fn<Clock["sleep"]>>;
} {
  const sleepMock = vi.fn<Clock["sleep"]>(
    (_delayMs: number, signal?: AbortSignal): Promise<void> =>
      new Promise<void>((_resolve, reject) => {
        if (signal?.aborted) {
          reject(abortReason(signal));
          return;
        }
        if (signal === undefined) {
          reject(new Error("Expected sleep to receive an AbortSignal"));
          return;
        }
        signal.addEventListener("abort", () => reject(abortReason(signal)), {
          once: true,
        });
      }),
  );
  return { clock: { now: () => startMs, sleep: sleepMock }, sleepMock };
}

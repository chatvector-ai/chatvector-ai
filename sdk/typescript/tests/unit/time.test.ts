import { afterEach, describe, expect, it, vi } from "vitest";

import {
  abortReason,
  sleep,
  systemClock,
  throwIfAborted,
} from "../../src/internal/time.js";
import {
  captureRejection,
  flushAsyncWork,
} from "../helpers/mock-fetch.js";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("abort-aware time primitives", () => {
  it("uses Date.now for the system clock", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-14T12:00:00Z"));
    expect(systemClock.now()).toBe(Date.parse("2026-07-14T12:00:00Z"));
  });

  it("resolves only after the requested delay", async () => {
    vi.useFakeTimers();
    let resolved = false;
    const promise = sleep(500).then(() => {
      resolved = true;
    });

    await vi.advanceTimersByTimeAsync(499);
    expect(resolved).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await promise;
    expect(resolved).toBe(true);
  });

  it("treats zero as an event-loop yield", async () => {
    vi.useFakeTimers();
    let resolved = false;
    const promise = sleep(0).then(() => {
      resolved = true;
    });
    await flushAsyncWork();
    expect(resolved).toBe(false);
    await vi.advanceTimersByTimeAsync(0);
    await promise;
    expect(resolved).toBe(true);
  });

  it.each([-1, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects invalid delay %s",
    async (delay) => {
      await expect(sleep(delay)).rejects.toBeInstanceOf(RangeError);
    },
  );

  it("rejects a pre-aborted signal with its original reason", async () => {
    const controller = new AbortController();
    const reason = new DOMException("caller stopped", "AbortError");
    controller.abort(reason);
    await expect(sleep(100, controller.signal)).rejects.toBe(reason);
    expect(() => throwIfAborted(controller.signal)).toThrow(reason);
    expect(abortReason(controller.signal)).toBe(reason);
  });

  it("preserves an explicit null abort reason", async () => {
    const controller = new AbortController();
    controller.abort(null);
    expect(abortReason(controller.signal)).toBeNull();
    expect(await captureRejection(sleep(100, controller.signal))).toBeNull();
    let caught: unknown = Symbol("not thrown");
    try {
      throwIfAborted(controller.signal);
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeNull();
  });

  it("cancels an active sleep without leaving a timer", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const promise = sleep(10_000, controller.signal);
    expect(vi.getTimerCount()).toBe(1);
    controller.abort();
    await expect(promise).rejects.toBe(controller.signal.reason);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("chunks delays that exceed Node's timer maximum", async () => {
    const maxTimerDelay = 2_147_483_647;
    const observedDelays: number[] = [];
    vi.spyOn(globalThis, "setTimeout").mockImplementation(
      ((callback: (...args: unknown[]) => void, delay?: number) => {
        observedDelays.push(delay ?? 0);
        queueMicrotask(callback);
        return 1 as unknown as ReturnType<typeof setTimeout>;
      }) as typeof setTimeout,
    );

    await sleep(maxTimerDelay + 25);
    expect(observedDelays).toEqual([maxTimerDelay, 25]);
  });
});

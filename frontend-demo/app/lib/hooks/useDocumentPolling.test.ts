import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDocumentPolling } from "./useDocumentPolling";

const mockGetDocumentStatus = vi.fn();

vi.mock("../api", () => ({
  getDocumentStatus: (...args: unknown[]) => mockGetDocumentStatus(...args),
  API_BASE: "http://localhost:8000",
  DocumentNotFoundError: class DocumentNotFoundError extends Error {
    name = "DocumentNotFoundError";
  },
}));

describe("useDocumentPolling", () => {
  const originalEventSource = globalThis.EventSource;

  beforeEach(() => {
    mockGetDocumentStatus.mockReset();
    // Force the authenticated polling path; EventSource cannot send auth headers.
    delete (globalThis as { EventSource?: typeof EventSource }).EventSource;
  });

  afterEach(() => {
    globalThis.EventSource = originalEventSource;
    vi.useRealTimers();
  });

  it("maps status-only backend payloads without a stage field", async () => {
    vi.useFakeTimers();

    mockGetDocumentStatus
      .mockResolvedValueOnce({
        status: "embedding",
        chunks: { processed: 2, total: 10 },
      })
      .mockResolvedValueOnce({
        status: "completed",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:01Z",
      });

    const { result } = renderHook(() =>
      useDocumentPolling("doc-1", "/documents/doc-1/status", "processing"),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.stage).toBe("embedding");
    expect(result.current.status).toBe("processing");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(result.current.stage).toBe("completed");
    expect(result.current.status).toBe("ready");
    expect(mockGetDocumentStatus).toHaveBeenCalledWith("/documents/doc-1/status");
  });

  it("stays in processing while status_detail is replacement_in_progress and resolves to ready on cutover", async () => {
    vi.useFakeTimers();

    mockGetDocumentStatus
      .mockResolvedValueOnce({
        status: "completed",
        status_detail: "replacement_in_progress",
        queue_position: 2,
      })
      .mockResolvedValueOnce({
        status: "completed",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:02Z",
      });

    const { result } = renderHook(() =>
      useDocumentPolling("doc-1", "/documents/doc-1/status", "processing"),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.status).toBe("processing");
    expect(result.current.stage).toBe("queued");
    expect(result.current.queuePosition).toBe(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(result.current.status).toBe("ready");
    expect(result.current.stage).toBe("completed");
    expect(mockGetDocumentStatus).toHaveBeenCalledTimes(2);
  });

  it("keeps SSE stream open during replacement_in_progress and surfaces replacement_failed", async () => {
    const listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
    const closeSpy = vi.fn();

    class MockEventSource {
      url: string;
      close = closeSpy;
      constructor(url: string) {
        this.url = url;
      }
      addEventListener(type: string, cb: (event: MessageEvent) => void) {
        listeners[type] = listeners[type] ?? [];
        listeners[type].push(cb);
      }
    }

    globalThis.EventSource = MockEventSource as unknown as typeof EventSource;

    const { result } = renderHook(() =>
      useDocumentPolling("doc-1", "/documents/doc-1/status", "processing"),
    );

    act(() => {
      listeners.status?.[0]?.({
        data: JSON.stringify({
          status: "completed",
          status_detail: "replacement_in_progress",
          queue_position: 1,
        }),
      } as MessageEvent);
    });

    expect(result.current.status).toBe("processing");
    expect(result.current.stage).toBe("queued");
    expect(result.current.errorMessage).toBeUndefined();
    expect(closeSpy).not.toHaveBeenCalled();

    act(() => {
      listeners.status?.[0]?.({
        data: JSON.stringify({
          status: "completed",
          status_detail: "replacement_failed",
          error: {
            stage: "embedding",
            message: "Embedding provider exploded",
          },
        }),
      } as MessageEvent);
    });

    expect(result.current.status).toBe("failed");
    expect(result.current.stage).toBe("embedding");
    expect(result.current.errorMessage).toBe("Embedding provider exploded");
    expect(closeSpy).toHaveBeenCalledTimes(1);
  });
});

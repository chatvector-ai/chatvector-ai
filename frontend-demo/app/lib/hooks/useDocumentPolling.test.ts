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

  it("maps retrying as a non-terminal stage and transitions cleanly to failed", async () => {
    vi.useFakeTimers();

    mockGetDocumentStatus
      .mockResolvedValueOnce({
        status: "embedding",
        chunks: { processed: 4, total: 10 },
      })
      .mockResolvedValueOnce({
        status: "retrying",
      })
      .mockResolvedValueOnce({
        status: "failed",
        error: {
          stage: "embedding",
          message: "Embedding provider timeout",
        },
      });

    const { result } = renderHook(() =>
      useDocumentPolling("doc-2", "/documents/doc-2/status", "processing"),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.stage).toBe("embedding");
    expect(result.current.status).toBe("processing");
    expect(result.current.completedStages).toEqual([
      "uploading",
      "queued",
      "extracting",
      "chunking",
    ]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(result.current.stage).toBe("retrying");
    expect(result.current.status).toBe("processing");
    expect(result.current.errorMessage).toBeUndefined();
    expect(result.current.completedStages).toEqual([
      "uploading",
      "queued",
      "extracting",
      "chunking",
    ]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(result.current.stage).toBe("embedding");
    expect(result.current.status).toBe("failed");
    expect(result.current.errorMessage).toBe("Embedding provider timeout");
    expect(result.current.completedStages).toEqual([
      "uploading",
      "queued",
      "extracting",
      "chunking",
    ]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(mockGetDocumentStatus).toHaveBeenCalledTimes(3);
  });

  it("recovers from retrying when a retry attempt succeeds", async () => {
    vi.useFakeTimers();

    mockGetDocumentStatus
      .mockResolvedValueOnce({
        status: "retrying",
      })
      .mockResolvedValueOnce({
        status: "completed",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:02Z",
      });

    const { result } = renderHook(() =>
      useDocumentPolling("doc-3", "/documents/doc-3/status", "processing"),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.stage).toBe("retrying");
    expect(result.current.status).toBe("processing");
    expect(result.current.completedStages).toEqual([]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(result.current.stage).toBe("completed");
    expect(result.current.status).toBe("ready");
    expect(result.current.completedStages).not.toContain("retrying");
  });

  it("keeps SSE stream open while retrying and closes on terminal failure", async () => {
    const listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
    const closeSpy = vi.fn();

    class MockEventSource {
      url: string;
      constructor(url: string) {
        this.url = url;
      }
      addEventListener(type: string, handler: (event: MessageEvent) => void) {
        listeners[type] = listeners[type] ?? [];
        listeners[type].push(handler);
      }
      close() {
        closeSpy();
      }
    }

    globalThis.EventSource = MockEventSource as unknown as typeof EventSource;

    const { result } = renderHook(() =>
      useDocumentPolling("doc-4", "/documents/doc-4/status", "processing"),
    );

    const emitStatus = (payload: unknown) => {
      for (const handler of listeners.status ?? []) {
        handler({ data: JSON.stringify(payload) } as MessageEvent);
      }
    };

    await act(async () => {
      emitStatus({ status: "retrying" });
    });

    expect(result.current.stage).toBe("retrying");
    expect(result.current.status).toBe("processing");
    expect(closeSpy).not.toHaveBeenCalled();

    await act(async () => {
      emitStatus({
        status: "failed",
        error: { stage: "storing", message: "Vector store write failed" },
      });
    });

    expect(result.current.stage).toBe("storing");
    expect(result.current.status).toBe("failed");
    expect(result.current.errorMessage).toBe("Vector store write failed");
    expect(closeSpy).toHaveBeenCalledOnce();
  });
});


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

  it("exposes file_name from status and replaces it after cutover", async () => {
    vi.useFakeTimers();

    mockGetDocumentStatus
      .mockResolvedValueOnce({
        status: "embedding",
        file_name: "notes.txt",
      })
      .mockResolvedValueOnce({
        status: "embedding",
        file_name: "   ",
      })
      .mockResolvedValueOnce({
        status: "completed",
        file_name: "notes-v2.txt",
      });

    const { result } = renderHook(() =>
      useDocumentPolling("doc-name", "/documents/doc-name/status", "processing"),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.fileName).toBe("notes.txt");
    expect(result.current.status).toBe("processing");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(result.current.fileName).toBe("notes.txt");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(result.current.fileName).toBe("notes-v2.txt");
    expect(result.current.status).toBe("ready");
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
      emitStatus({ status: "retrying", file_name: "notes.txt" });
    });

    expect(result.current.stage).toBe("retrying");
    expect(result.current.status).toBe("processing");
    expect(result.current.fileName).toBe("notes.txt");
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

  it("stays in processing while status_detail is replacement_in_progress and resolves to ready on cutover", async () => {
    vi.useFakeTimers();

    mockGetDocumentStatus
      .mockResolvedValueOnce({
        status: "completed",
        status_detail: "replacement_in_progress",
        queue_position: 2,
        file_name: "notes.txt",
      })
      .mockResolvedValueOnce({
        status: "completed",
        file_name: "notes-v2.txt",
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
    expect(result.current.fileName).toBe("notes.txt");
    expect(result.current.apiStatus).toBe("completed");
    expect(result.current.statusDetail).toBe("replacement_in_progress");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });

    expect(result.current.status).toBe("ready");
    expect(result.current.stage).toBe("completed");
    expect(result.current.fileName).toBe("notes-v2.txt");
    expect(result.current.statusDetail).toBeUndefined();
    expect(mockGetDocumentStatus).toHaveBeenCalledTimes(2);
  });

  it("keeps the SSE stream open during replacement_in_progress and surfaces replacement_failed", async () => {
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
          file_name: "notes.txt",
        }),
      } as MessageEvent);
    });

    expect(result.current.status).toBe("processing");
    expect(result.current.stage).toBe("queued");
    expect(result.current.errorMessage).toBeUndefined();
    expect(result.current.apiStatus).toBe("completed");
    expect(result.current.statusDetail).toBe("replacement_in_progress");
    expect(closeSpy).not.toHaveBeenCalled();

    act(() => {
      listeners.status?.[0]?.({
        data: JSON.stringify({
          status: "completed",
          status_detail: "replacement_failed",
          file_name: "notes.txt",
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
    expect(result.current.apiStatus).toBe("completed");
    expect(result.current.statusDetail).toBe("replacement_failed");
    expect(result.current.fileName).toBe("notes.txt");
    expect(closeSpy).toHaveBeenCalledTimes(1);
  });

  it("does not keep a stale ready status when the same document starts processing again", async () => {
    vi.useFakeTimers();

    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      file_name: "notes.txt",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:01Z",
    });

    const { result, rerender } = renderHook(
      ({ status }: { status: "processing" | "ready" }) =>
        useDocumentPolling("doc-1", "/documents/doc-1/status", status),
      { initialProps: { status: "processing" } },
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.status).toBe("ready");

    rerender({ status: "ready" });

    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      status_detail: "replacement_in_progress",
      file_name: "notes.txt",
    });

    rerender({ status: "processing" });

    expect(result.current.status).not.toBe("ready");

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.status).toBe("processing");
    expect(result.current.statusDetail).toBe("replacement_in_progress");
    expect(result.current.apiStatus).toBe("completed");
  });
});


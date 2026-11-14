import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProxyClient } from "../src/proxy-client.js";
import { useProxyChat } from "../src/hooks/useProxyChat.js";

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("useProxyChat", () => {
  it("accumulates mocked streaming tokens from the proxy", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/chat/stream") && init?.method === "POST") {
        return sseResponse([
          'event: token\ndata: "Hello"\n\n',
          'event: token\ndata: " world"\n\n',
          'event: complete\ndata: {"session_id":"sess-1","sources":[],"latency_ms":12,"model":"test"}\n\n',
        ]);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const client = new ProxyClient({
      baseUrl: "http://app.test",
      getUserId: () => "user-1",
      fetchImpl,
    });

    const onSessionId = vi.fn();
    const { result } = renderHook(() =>
      useProxyChat({ client, onSessionId }),
    );

    await act(async () => {
      await result.current.send({
        question: "Hi",
        docId: "doc-1",
      });
    });

    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    expect(result.current.answer).toBe("Hello world");
    expect(result.current.error).toBeNull();
    expect(onSessionId).toHaveBeenCalledWith("sess-1");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(String(fetchImpl.mock.calls[0]?.[0])).toBe(
      "http://app.test/api/chat/stream",
    );
  });

  it("handles non-streaming fallback when status is ok", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/chat/stream") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            error: { code: "streaming_disabled", message: "Streaming disabled" },
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/api/chat") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            sessionId: "sess-2",
            response: {
              question: "Hi",
              docId: "doc-1",
              chunks: 1,
              answer: "Fallback answer",
              sources: [{ fileName: "doc.txt", pageNumber: 1, score: 0.9 }],
              latencyMs: 15,
              model: "test",
              status: "ok",
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const client = new ProxyClient({
      baseUrl: "http://app.test",
      getUserId: () => "user-1",
      fetchImpl,
    });

    const onSessionId = vi.fn();
    const { result } = renderHook(() =>
      useProxyChat({ client, onSessionId }),
    );

    await act(async () => {
      await result.current.send({
        question: "Hi",
        docId: "doc-1",
      });
    });

    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    expect(result.current.answer).toBe("Fallback answer");
    expect(result.current.sources).toEqual([
      { fileName: "doc.txt", pageNumber: 1, score: 0.9 },
    ]);
    expect(result.current.error).toBeNull();
    expect(onSessionId).toHaveBeenCalledWith("sess-2");
  });

  it("sets error and omits answer when non-streaming fallback returns status error", async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/chat/stream") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            error: { code: "streaming_disabled", message: "Streaming disabled" },
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/api/chat") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            sessionId: "sess-3",
            response: {
              question: "Hi",
              docId: "doc-1",
              chunks: 0,
              answer: "",
              sources: [],
              latencyMs: 10,
              model: "test",
              status: "error",
              error: {
                code: "anchor_document_excluded_by_filter",
                message: "Active document is excluded by filter",
              },
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const client = new ProxyClient({
      baseUrl: "http://app.test",
      getUserId: () => "user-1",
      fetchImpl,
    });

    const onSessionId = vi.fn();
    const { result } = renderHook(() =>
      useProxyChat({ client, onSessionId }),
    );

    await act(async () => {
      await result.current.send({
        question: "Hi",
        docId: "doc-1",
      });
    });

    await waitFor(() => {
      expect(result.current.isStreaming).toBe(false);
    });

    expect(result.current.answer).toBe("");
    expect(result.current.sources).toEqual([]);
    expect(result.current.error).toBe("Active document is excluded by filter");
    expect(onSessionId).toHaveBeenCalledWith("sess-3");
  });
});

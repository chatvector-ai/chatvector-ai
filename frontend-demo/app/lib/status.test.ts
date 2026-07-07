import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getSystemStatus, StatusFetchError, statusErrorTitle } from "./status";

const HEALTHY_STATUS = {
  status: "healthy",
  components: {
    api: "ok",
    database: "connected",
    queue: "connected",
    embeddings: "ok",
    llm: "ok",
  },
  health_checks: {
    embedding: { status: "ok", latency_ms: 12 },
    llm: { status: "ok", latency_ms: 45 },
    redis: { status: "ok", latency_ms: 3 },
  },
  metrics: {
    document_queue: 0,
    workers_active: 1,
    memory_usage: 42,
    documents_indexed: 128,
    total_queries: null,
  },
  uptime: "2h 15m",
  version: "1.0.0",
};

const DEGRADED_STATUS = {
  ...HEALTHY_STATUS,
  status: "degraded",
  components: {
    ...HEALTHY_STATUS.components,
    llm: "error",
  },
  health_checks: {
    ...HEALTHY_STATUS.health_checks,
    llm: { status: "error", error: "timeout" },
  },
};

describe("getSystemStatus", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns healthy JSON status payloads", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(HEALTHY_STATUS), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(getSystemStatus()).resolves.toEqual(HEALTHY_STATUS);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/status"),
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Accept: "application/json",
        }),
      })
    );
  });

  it("returns degraded JSON status payloads", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify(DEGRADED_STATUS), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(getSystemStatus()).resolves.toEqual(DEGRADED_STATUS);
  });

  it("throws a network failure message when fetch rejects", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("fetch failed"));

    await expect(getSystemStatus()).rejects.toMatchObject({
      name: "StatusFetchError",
      kind: "network",
      message: expect.stringContaining("Unable to connect to the ChatVector backend."),
    });
  });

  it("throws for non-2xx JSON responses", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Service unavailable" }), {
        status: 503,
        statusText: "Service Unavailable",
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(getSystemStatus()).rejects.toMatchObject({
      name: "StatusFetchError",
      kind: "http_error",
      httpStatus: 503,
      message: expect.stringContaining("HTTP 503"),
    });
  });

  it("throws for HTML responses without surfacing raw markup", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response('<pre style="font-family: monospace;">System Status</pre>', {
        status: 502,
        headers: { "Content-Type": "text/html; charset=utf-8" },
      })
    );

    await expect(getSystemStatus()).rejects.toMatchObject({
      name: "StatusFetchError",
      kind: "unexpected_response",
      httpStatus: 502,
      contentType: "text/html; charset=utf-8",
      message: expect.stringContaining("Expected JSON but received text/html"),
    });

    await expect(getSystemStatus()).rejects.not.toMatchObject({
      message: expect.stringContaining("<pre"),
    });
  });

  it("reports HTML bodies even when the Content-Type claims JSON", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response('<pre style="font-family: monospace;">System Status</pre>', {
        status: 502,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(getSystemStatus()).rejects.toMatchObject({
      name: "StatusFetchError",
      kind: "unexpected_response",
      httpStatus: 502,
      message: expect.stringContaining("Expected JSON but received text/html"),
    });
  });

  it("throws for plain-text responses", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response("upstream connect error", {
        status: 502,
        headers: { "Content-Type": "text/plain" },
      })
    );

    await expect(getSystemStatus()).rejects.toMatchObject({
      name: "StatusFetchError",
      kind: "unexpected_response",
      httpStatus: 502,
      message: expect.stringContaining("Expected JSON but received text/plain"),
    });
  });

  it("throws for empty responses", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response("", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(getSystemStatus()).rejects.toMatchObject({
      name: "StatusFetchError",
      kind: "unexpected_response",
      httpStatus: 200,
      message: expect.stringContaining("empty response"),
    });
  });

  it("throws for invalid JSON responses", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response("{not-json", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(getSystemStatus()).rejects.toMatchObject({
      name: "StatusFetchError",
      kind: "invalid_json",
      httpStatus: 200,
      message: expect.stringContaining("was not valid JSON"),
    });

    await expect(getSystemStatus()).rejects.not.toMatchObject({
      message: expect.stringContaining("Unexpected token"),
    });
  });

  it("uses StatusFetchError for typed error handling", () => {
    const err = new StatusFetchError("boom", "network");
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(StatusFetchError);
    expect(err.kind).toBe("network");
  });

  it("rejects JSON payloads that do not match the status schema", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({ status: "unknown", message: "nope" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(getSystemStatus()).rejects.toMatchObject({
      name: "StatusFetchError",
      kind: "invalid_json",
      message: expect.stringContaining("did not look like a system status response"),
    });
  });
});

describe("statusErrorTitle", () => {
  it.each([
    ["network", "Backend Unreachable"],
    ["unexpected_response", "Unexpected Response"],
    ["invalid_json", "Unreadable Response"],
    ["http_error", "Backend Error"],
  ] as const)("maps %s to a user-facing heading", (kind, title) => {
    expect(statusErrorTitle(kind)).toBe(title);
  });
});

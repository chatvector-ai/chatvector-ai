import { describe, expect, it } from "vitest";

import { ChatVectorClient } from "../../src/index.js";
import {
  SESSION_ID,
  secondSessionPayload,
  sessionPayload,
} from "../fixtures/payloads.js";
import {
  captureRejection,
  createFetchMock,
  emptyResponse,
  getFetchCall,
  getJsonBody,
  jsonResponse,
} from "../helpers/mock-fetch.js";

function makeClient(fetch: typeof globalThis.fetch): ChatVectorClient {
  return new ChatVectorClient({
    baseUrl: "https://api.chatvector.test",
    fetch,
    retry: false,
  });
}

describe("session methods", () => {
  it("creates a session with an explicit empty JSON body", async () => {
    const fetch = createFetchMock(
      jsonResponse(sessionPayload, { status: 201 }),
    );
    const result = await makeClient(fetch).createSession();
    const { url, init } = getFetchCall(fetch);
    expect(url).toBe("https://api.chatvector.test/sessions");
    expect(init.method).toBe("POST");
    expect(getJsonBody(init)).toEqual({});
    expect(result).toEqual({
      id: SESSION_ID,
      tenantId: "tenant-1",
      createdAt: "2026-07-14T10:00:00+00:00",
      lastActive: "2026-07-14T10:01:00+00:00",
      metadata: { source: "sdk" },
      documentIds: [sessionPayload.document_ids[0]],
      _raw: sessionPayload,
    });
  });

  it("serializes a caller-provided session ID", async () => {
    const fetch = createFetchMock(
      jsonResponse({ ...sessionPayload, id: "custom-session" }, { status: 201 }),
    );
    await makeClient(fetch).createSession({ sessionId: "custom-session" });
    expect(getJsonBody(getFetchCall(fetch).init)).toEqual({
      session_id: "custom-session",
    });
  });

  it("gets a URL-encoded session and preserves its raw metadata", async () => {
    const fetch = createFetchMock(jsonResponse(sessionPayload));
    const result = await makeClient(fetch).getSession("session/with space?");
    expect(getFetchCall(fetch).url).toBe(
      "https://api.chatvector.test/sessions/session%2Fwith%20space%3F",
    );
    expect(result.metadata).toEqual({ source: "sdk" });
    expect(result.documentIds).toEqual(sessionPayload.document_ids);
    expect(result._raw).toEqual(sessionPayload);
  });

  it("returns the direct unpaginated list response with nested raw sessions", async () => {
    const payload = {
      sessions: [sessionPayload, secondSessionPayload, "ignored"],
      future_list_field: "raw",
    };
    const fetch = createFetchMock(jsonResponse(payload));
    const result = await makeClient(fetch).listSessions();
    const { url, init } = getFetchCall(fetch);
    expect(url).toBe("https://api.chatvector.test/sessions");
    expect(init.method).toBe("GET");
    expect(url).not.toContain("?");
    expect(result.sessions).toHaveLength(2);
    expect(result.sessions[0]?._raw).toEqual(sessionPayload);
    expect(result.sessions[1]).toMatchObject({
      id: "session-2",
      tenantId: null,
      metadata: {},
      documentIds: [],
      _raw: secondSessionPayload,
    });
    expect(result._raw).toEqual(payload);
  });

  it("maps malformed optional session fields to safe defaults", async () => {
    const payload = {
      id: SESSION_ID,
      tenant_id: 123,
      created_at: null,
      last_active: null,
      metadata: [],
      document_ids: ["doc-1", 2, null],
    };
    const result = await makeClient(
      createFetchMock(jsonResponse(payload)),
    ).getSession(SESSION_ID);
    expect(result).toMatchObject({
      id: SESSION_ID,
      tenantId: null,
      createdAt: "",
      lastActive: "",
      metadata: {},
      documentIds: ["doc-1"],
    });
  });

  it("deletes a URL-encoded session and resolves undefined on 204", async () => {
    const fetch = createFetchMock(emptyResponse());
    const result = await makeClient(fetch).deleteSession("session/one");
    expect(result).toBeUndefined();
    expect(getFetchCall(fetch).url).toBe(
      "https://api.chatvector.test/sessions/session%2Fone",
    );
    expect(getFetchCall(fetch).init.method).toBe("DELETE");
  });

  it.each([
    ["get", ""],
    ["delete", ""],
  ] as const)("rejects an empty ID for %s before fetch", async (method, id) => {
    const fetch = createFetchMock(jsonResponse(sessionPayload));
    const client = makeClient(fetch);
    const promise =
      method === "get" ? client.getSession(id) : client.deleteSession(id);
    expect(await captureRejection(promise)).toBeInstanceOf(TypeError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not retry session creation or deletion", async () => {
    const createFetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
    );
    const deleteFetch = createFetchMock(
      jsonResponse({ detail: "busy" }, { status: 503 }),
    );
    const createClient = new ChatVectorClient({
      baseUrl: "https://api.chatvector.test",
      fetch: createFetch,
      retry: { maxRetries: 5 },
    });
    const deleteClient = new ChatVectorClient({
      baseUrl: "https://api.chatvector.test",
      fetch: deleteFetch,
      retry: { maxRetries: 5 },
    });
    await captureRejection(createClient.createSession());
    await captureRejection(deleteClient.deleteSession(SESSION_ID));
    expect(createFetch).toHaveBeenCalledTimes(1);
    expect(deleteFetch).toHaveBeenCalledTimes(1);
  });
});

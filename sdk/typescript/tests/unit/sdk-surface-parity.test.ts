import { describe, expect, it } from "vitest";

import { ChatVectorClient } from "../../src/index.js";
import {
  DOCUMENT_ID,
  SESSION_ID,
  completedStatusPayload,
  uploadAcceptedPayload,
} from "../fixtures/payloads.js";
import {
  createFetchMock,
  getFetchCall,
  getJsonBody,
  jsonResponse,
  sseResponse,
} from "../helpers/mock-fetch.js";

function makeClient(fetch: typeof globalThis.fetch): ChatVectorClient {
  return new ChatVectorClient({
    baseUrl: "https://api.chatvector.test",
    apiKey: "test-key",
    fetch,
    retry: false,
  });
}

describe("SDK surface parity", () => {
  it("listDocuments and deleteDocument hit backend document routes", async () => {
    const listPayload = {
      tenant_id: "tenant-1",
      documents: [
        {
          document_id: DOCUMENT_ID,
          file_name: "guide.pdf",
          status: "completed",
        },
      ],
    };
    const fetch = createFetchMock(
      jsonResponse(listPayload),
      new Response(null, { status: 204 }),
    );
    const client = makeClient(fetch);
    const listed = await client.listDocuments();
    expect(listed.tenantId).toBe("tenant-1");
    expect(listed.documents[0]?.documentId).toBe(DOCUMENT_ID);
    await client.deleteDocument(DOCUMENT_ID);
    expect(getFetchCall(fetch, 0).url).toBe(
      "https://api.chatvector.test/documents",
    );
    expect(getFetchCall(fetch, 1).url).toBe(
      `https://api.chatvector.test/documents/${DOCUMENT_ID}`,
    );
    expect(getFetchCall(fetch, 1).init.method).toBe("DELETE");
  });

  it("getSessionHistory maps session history messages", async () => {
    const fetch = createFetchMock(
      jsonResponse({
        messages: [
          {
            id: "msg-1",
            role: "user",
            content: "Hello",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      }),
    );
    const history = await makeClient(fetch).getSessionHistory(SESSION_ID);
    expect(getFetchCall(fetch).url).toBe(
      `https://api.chatvector.test/sessions/${encodeURIComponent(SESSION_ID)}/history`,
    );
    expect(history.messages[0]).toMatchObject({
      id: "msg-1",
      role: "user",
      content: "Hello",
      createdAt: "2026-01-01T00:00:00Z",
    });
    expect(history.messages[0]?.sources).toBeUndefined();
  });

  it("streamDocumentStatus parses terminal SSE status events", async () => {
    const body = [
      "event: status",
      `data: ${JSON.stringify({ document_id: DOCUMENT_ID, status: "queued" })}`,
      "",
      "event: status",
      `data: ${JSON.stringify(completedStatusPayload)}`,
      "",
    ].join("\n");
    const fetch = createFetchMock(sseResponse(body));
    const events = [];
    for await (const event of makeClient(fetch).streamDocumentStatus(DOCUMENT_ID)) {
      events.push(event.status);
    }
    expect(getFetchCall(fetch).url).toBe(
      `https://api.chatvector.test/documents/${DOCUMENT_ID}/status/stream`,
    );
    expect(events).toEqual(["queued", "completed"]);
  });

  it("streamDocumentStatus maps file_name when present and omits it when absent", async () => {
    const named = {
      document_id: DOCUMENT_ID,
      status: "completed",
      file_name: "notes.txt",
    };
    const unnamed = { document_id: DOCUMENT_ID, status: "queued" };
    const body = [
      "event: status",
      `data: ${JSON.stringify(unnamed)}`,
      "",
      "event: status",
      `data: ${JSON.stringify(named)}`,
      "",
    ].join("\n");
    const fetch = createFetchMock(sseResponse(body));
    const events = [];
    for await (const event of makeClient(fetch).streamDocumentStatus(DOCUMENT_ID)) {
      events.push(event);
    }
    expect(events[0]?.fileName).toBeUndefined();
    expect(events[0]?.status).toBe("queued");
    expect(events[1]?.fileName).toBe("notes.txt");
    expect(events[1]?.status).toBe("completed");
  });

  it("streamDocumentStatus types metadata and keeps unknown raw fields", async () => {
    const payload = {
      document_id: DOCUMENT_ID,
      status: "completed",
      metadata: { department: "legal" },
      future_field: { trace: "abc" },
    };
    const body = ["event: status", `data: ${JSON.stringify(payload)}`, ""].join(
      "\n",
    );
    const fetch = createFetchMock(sseResponse(body));
    const events = [];
    for await (const event of makeClient(fetch).streamDocumentStatus(DOCUMENT_ID)) {
      events.push(event);
    }
    expect(events).toEqual([
      {
        documentId: DOCUMENT_ID,
        status: "completed",
        metadata: { department: "legal" },
        _raw: payload,
      },
    ]);
  });

  it("uploadDocument sends X-Session-Id when sessionId is set", async () => {
    const fetch = createFetchMock(jsonResponse(uploadAcceptedPayload, { status: 202 }));
    await makeClient(fetch).uploadDocument({
      data: new Uint8Array([1, 2, 3]),
      fileName: "notes.txt",
      sessionId: "sess-upload",
    });
    expect(new Headers(getFetchCall(fetch).init.headers).get("X-Session-Id")).toBe(
      "sess-upload",
    );
  });

  it("debugRetrieval parses typed retrievalDebug and preserves unknown keys", async () => {
    const fetch = createFetchMock(
      jsonResponse({
        question: "Q",
        doc_id: DOCUMENT_ID,
        chunks: 1,
        answer: "A",
        sources: [
          {
            file_name: "guide.pdf",
            page_number: 1,
            chunk_index: 0,
            score: 0.9,
            score_type: "hybrid_rrf",
            vector_score: 0.8,
            rrf_score: 0.7,
          },
        ],
        latency_ms: 10,
        model: "gpt-test",
        status: "ok",
        retrieval_debug: {
          original_query: "Q",
          future_field: { trace: true },
        },
      }),
    );
    const result = await makeClient(fetch).chat({
      question: "Q",
      docId: DOCUMENT_ID,
      debugRetrieval: true,
    });
    expect(getJsonBody(getFetchCall(fetch).init)).toMatchObject({
      debug_retrieval: true,
    });
    expect(result.retrievalDebug).toMatchObject({
      originalQuery: "Q",
      original_query: "Q",
      future_field: { trace: true },
    });
    expect(result.sources[0]).toMatchObject({
      vectorScore: 0.8,
      rrfScore: 0.7,
    });
  });
});

import { describe, expect, it } from "vitest";

import {
  ChatVectorClient,
  type ChatVectorClientOptions,
} from "../../src/index.js";

const baseUrl = process.env.CHATVECTOR_INTEGRATION_BASE_URL?.replace(/\/+$/, "");
const apiKey = process.env.CHATVECTOR_INTEGRATION_API_KEY;
const describeLive = baseUrl && apiKey ? describe : describe.skip;

describeLive("live ChatVector API", () => {
  it(
    "uploads, waits, creates a session, chats, and cleans up disposable state",
    async () => {
      const options: ChatVectorClientOptions = {
        baseUrl: baseUrl!,
        apiKey: apiKey!,
      };
      const client = new ChatVectorClient(options);
      let documentId: string | undefined;
      let sessionId: string | undefined;

      try {
        const upload = await client.uploadDocument({
          data: new TextEncoder().encode(
            "ChatVector integration fixture. The launch code name is Aurora.",
          ),
          fileName: `chatvector-sdk-${Date.now()}.txt`,
          contentType: "text/plain",
        });
        documentId = upload.documentId;
        expect(documentId).not.toBe("");
        expect(upload.statusEndpoint).toContain(documentId);

        const ready = await client.waitForReady(documentId, {
          timeoutMs: 120_000,
          pollIntervalMs: 1_000,
        });
        expect(ready.status).toBe("completed");

        const session = await client.createSession();
        sessionId = session.id;
        expect(sessionId).not.toBe("");

        const chat = await client.chat({
          question: "What is the launch code name?",
          docId: documentId,
          sessionId,
          matchCount: 3,
          scope: "session",
        });
        expect(chat.status).toBe("ok");
        expect(chat.docId).toBe(documentId);
        expect(chat.answer).not.toBe("");
      } finally {
        if (sessionId !== undefined) {
          await client.deleteSession(sessionId).catch(() => undefined);
        }
        if (documentId !== undefined) {
          const headers = new Headers({ Accept: "application/json" });
          headers.set("Authorization", `Bearer ${apiKey!}`);
          await fetch(`${baseUrl!}/documents/${encodeURIComponent(documentId)}`, {
            method: "DELETE",
            headers,
          }).catch(() => undefined);
        }
      }
    },
    150_000,
  );
});

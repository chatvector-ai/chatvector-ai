import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { ChatVectorAPIError, ChatVectorClient } from "../../src/index.js";
import { createUploadFormData } from "../../src/internal/upload.js";
import { DOCUMENT_ID, uploadAcceptedPayload } from "../fixtures/payloads.js";
import {
  captureRejection,
  createFetchMock,
  getFetchCall,
  getMultipartFile,
  jsonResponse,
} from "../helpers/mock-fetch.js";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((path) =>
      rm(path, { recursive: true, force: true }),
    ),
  );
});

function makeClient(fetch: typeof globalThis.fetch): ChatVectorClient {
  return new ChatVectorClient({
    baseUrl: "https://api.chatvector.test",
    apiKey: "test-key",
    fetch,
    retry: { maxRetries: 5 },
  });
}

describe("uploadDocument", () => {
  it("propagates a missing path error without making a request", async () => {
    const fetch = createFetchMock(jsonResponse(uploadAcceptedPayload));
    const missingPath = join(
      tmpdir(),
      `chatvector-sdk-missing-${process.pid}-${Date.now()}.pdf`,
    );
    await expect(
      makeClient(fetch).uploadDocument({ path: missingPath }),
    ).rejects.toBeInstanceOf(TypeError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("uploads replayable bytes as multipart and maps the accepted response", async () => {
    const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d]);
    let capturedFile: Awaited<ReturnType<typeof getMultipartFile>> | undefined;
    const fetch = createFetchMock(async (_input, init) => {
      capturedFile = await getMultipartFile(init ?? {});
      return jsonResponse(uploadAcceptedPayload, { status: 202 });
    });
    const result = await makeClient(fetch).uploadDocument({
      data: bytes,
      fileName: "guide.pdf",
    });

    const { url, init } = getFetchCall(fetch);
    expect(url).toBe("https://api.chatvector.test/ingest");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Accept")).toBe("application/json");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer test-key",
    );
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
    expect(capturedFile?.file.name).toBe("guide.pdf");
    expect(capturedFile?.file.type).toBe("application/pdf");
    expect(capturedFile?.bytes).toEqual(bytes);
    expect(result).toEqual({
      documentId: DOCUMENT_ID,
      status: "queued",
      message: "Accepted",
      queuePosition: 2,
      statusEndpoint: `/documents/${DOCUMENT_ID}/status`,
      _raw: uploadAcceptedPayload,
    });
  });

  it("prefers explicit contentType, then an existing Blob type", async () => {
    const explicit = await createUploadFormData({
      data: new Blob(["hello"], { type: "text/plain" }),
      fileName: "guide.txt",
      contentType: " application/pdf ",
    });
    const existing = await createUploadFormData({
      data: new Blob(["hello"], { type: "text/custom" }),
      fileName: "guide.bin",
    });
    const explicitFile = explicit.get("file") as File;
    const existingFile = existing.get("file") as File;
    expect(explicitFile.type).toBe("application/pdf");
    expect(existingFile.type).toBe("text/custom");
  });

  it("infers TXT case-insensitively and falls back to octet-stream", async () => {
    const text = await createUploadFormData({
      data: new Uint8Array([65]),
      fileName: "NOTES.TXT",
    });
    const unknown = await createUploadFormData({
      data: new Uint8Array([1]),
      fileName: "data.unknown",
    });
    expect((text.get("file") as File).type).toBe("text/plain");
    expect((unknown.get("file") as File).type).toBe(
      "application/octet-stream",
    );
  });

  it("opens path input with its basename and inferred MIME type", async () => {
    const directory = await mkdtemp(join(tmpdir(), "chatvector-upload-"));
    temporaryDirectories.push(directory);
    const path = join(directory, "Guide.PDF");
    const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d]);
    await writeFile(path, bytes);
    let captured: Awaited<ReturnType<typeof getMultipartFile>> | undefined;
    const fetch = createFetchMock(async (_input, init) => {
      captured = await getMultipartFile(init ?? {});
      return jsonResponse(uploadAcceptedPayload, { status: 202 });
    });
    await makeClient(fetch).uploadDocument({ path });
    expect(captured?.file.name).toBe("Guide.PDF");
    expect(captured?.file.type).toBe("application/pdf");
    expect(captured?.bytes).toEqual(bytes);
  });

  it("falls back only from /ingest 404 and rebuilds fresh replayable FormData", async () => {
    const forms: FormData[] = [];
    const payloads: Uint8Array[] = [];
    const capture = async (init?: RequestInit): Promise<void> => {
      const part = await getMultipartFile(init ?? {});
      forms.push(part.form);
      payloads.push(part.bytes);
    };
    const fetch = createFetchMock(
      async (_input, init) => {
        await capture(init);
        return jsonResponse({ detail: "Not Found" }, { status: 404 });
      },
      async (_input, init) => {
        await capture(init);
        return jsonResponse(uploadAcceptedPayload, { status: 202 });
      },
    );
    const source = new Uint8Array([1, 2, 3, 4]);
    await makeClient(fetch).uploadDocument({
      data: source,
      fileName: "notes.txt",
    });

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(getFetchCall(fetch, 0).url).toBe("https://api.chatvector.test/ingest");
    expect(getFetchCall(fetch, 1).url).toBe("https://api.chatvector.test/upload");
    expect(forms[0]).not.toBe(forms[1]);
    expect(payloads).toEqual([source, source]);
  });

  it.each([401, 429, 500, 503])(
    "does not fallback or retry when /ingest returns HTTP %i",
    async (status) => {
      const fetch = createFetchMock(
        jsonResponse({ detail: "failed" }, { status }),
      );
      const error = await captureRejection(
        makeClient(fetch).uploadDocument({
          data: new Uint8Array([1]),
          fileName: "notes.txt",
        }),
      );
      expect(error).toBeInstanceOf(ChatVectorAPIError);
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );

  it("does not start fallback after caller aborts during the 404 response", async () => {
    const controller = new AbortController();
    const fetch = createFetchMock(() => {
      controller.abort();
      return jsonResponse({ detail: "Not Found" }, { status: 404 });
    });
    const error = await captureRejection(
      makeClient(fetch).uploadDocument(
        { data: new Uint8Array([1]), fileName: "notes.txt" },
        { signal: controller.signal },
      ),
    );
    expect(error).toBe(controller.signal.reason);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    [null, "required"],
    [{}, "path or replayable data"],
    [{ path: "" }, "path"],
    [{ data: new Uint8Array([1]), fileName: "" }, "fileName"],
    [{ data: "not-bytes", fileName: "x.txt" }, "Uint8Array or Blob"],
  ])("validates malformed upload input before fetch", async (input, message) => {
    const fetch = createFetchMock(jsonResponse(uploadAcceptedPayload));
    const error = await captureRejection(
      makeClient(fetch).uploadDocument(input as never),
    );
    expect(error).toBeInstanceOf(TypeError);
    expect((error as Error).message).toContain(message);
    expect(fetch).not.toHaveBeenCalled();
  });
});

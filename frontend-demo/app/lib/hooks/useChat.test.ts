import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useChat } from "./useChat";
import { DEFAULT_RETRIEVAL_SETTINGS } from "../retrievalSettings";
import { DocumentNotFoundError, StreamingDisabledError } from "../api";

const mockSendMessageStream = vi.fn();
const mockSendMessage = vi.fn();
const mockGetSessionHistory = vi.fn();
const mockGetSession = vi.fn();
const mockGetDocumentStatus = vi.fn();
const mockGetUploadedDocument = vi.fn();
const mockPoll = vi.hoisted(() => ({
  status: "ready" as "processing" | "ready" | "failed",
  stage: "completed" as string | undefined,
  completedStages: [] as string[],
  chunks: undefined as { total: number; processed: number } | undefined,
  awaitingProcessing: false,
  processingTime: undefined as string | undefined,
  errorMessage: undefined as string | undefined,
  queuePosition: undefined as number | undefined,
  fileName: undefined as string | undefined,
  apiStatus: undefined as string | undefined,
  statusDetail: undefined as string | undefined,
}));

vi.mock("../api", () => ({
  deleteDocument: vi.fn(),
  sendMessage: (...args: unknown[]) => mockSendMessage(...args),
  sendMessageStream: (...args: unknown[]) => mockSendMessageStream(...args),
  getSessionHistory: (...args: unknown[]) => mockGetSessionHistory(...args),
  getSession: (...args: unknown[]) => mockGetSession(...args),
  getDocumentStatus: (...args: unknown[]) => mockGetDocumentStatus(...args),
  DocumentNotFoundError: class DocumentNotFoundError extends Error {},
  ChatError: class ChatError extends Error {
    code = "unexpected";
  },
  StreamingDisabledError: class StreamingDisabledError extends Error {
    name = "StreamingDisabledError";
  },
}));

vi.mock("./useDocumentPolling", () => ({
  useDocumentPolling: () => mockPoll,
}));

vi.mock("../documentStore", () => ({
  saveUploadedDocument: vi.fn(),
  removeUploadedDocument: vi.fn(),
  getUploadedDocument: (...args: unknown[]) => mockGetUploadedDocument(...args),
}));

const WELCOME_TEXT =
  "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it.";
const DOCUMENT_GONE_NOTICE =
  "The document attached to this session is no longer available. You can upload another.";
const DOCUMENT_UNAVAILABLE_NOTICE =
  "The document attached to this session could not be checked. You can upload another.";
const OPAQUE_RESTORE_NOTICE =
  "Could not restore the session document. You can upload a new one.";
const SESSION_HISTORY_FAILED_NOTICE =
  "This chat could not be loaded. You can upload a document and continue from here.";
const SESSION_DETAILS_FAILED_NOTICE =
  "This session could not be fully restored. You can upload a document to continue.";

function sessionPayload(sessionId: string, documentIds: string[] = []) {
  return {
    id: sessionId,
    created_at: "2026-01-01T00:00:00Z",
    last_active: "2026-01-01T00:00:00Z",
    metadata: {},
    document_ids: documentIds,
  };
}

describe("useChat", () => {
  beforeEach(() => {
    mockSendMessageStream.mockReset();
    mockSendMessage.mockReset();
    mockGetSessionHistory.mockResolvedValue({ messages: [] });
    mockGetSession.mockResolvedValue(sessionPayload("session-a"));
    mockGetDocumentStatus.mockReset();
    mockGetUploadedDocument.mockReset();
    mockGetUploadedDocument.mockReturnValue(undefined);
    mockPoll.status = "ready";
    mockPoll.stage = "completed";
    mockPoll.fileName = undefined;
    mockPoll.chunks = undefined;
    mockPoll.processingTime = undefined;
    mockPoll.errorMessage = undefined;
    mockPoll.apiStatus = undefined;
    mockPoll.statusDetail = undefined;
  });

  it("ignores a second synchronous send while a stream is in flight", async () => {
    mockSendMessageStream.mockImplementation(async function* () {
      yield { type: "token", text: "Hello" };
      yield {
        type: "complete",
        sources: [],
        latency_ms: 10,
        model: "m",
        _raw: {},
      };
    });

    const { result } = renderHook(
      ({ sessionId }) => useChat(sessionId, DEFAULT_RETRIEVAL_SETTINGS),
      { initialProps: { sessionId: "session-a" } },
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
      result.current.setInput("First question");
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    await act(async () => {
      void result.current.handleSend();
      void result.current.handleSend();
    });

    expect(mockSendMessageStream).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(result.current.inflight).toBe(false));
  });

  it("applies session history after switching sessions mid-flight", async () => {
    let releaseStream: (() => void) | undefined;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });

    mockSendMessageStream.mockImplementation(async function* () {
      await streamGate;
      yield { type: "token", text: "stale" };
    });

    mockGetSessionHistory.mockImplementation(async (sessionId: string) => ({
      messages:
        sessionId === "session-b"
          ? [{ id: "m-1", role: "assistant", content: "History for B" }]
          : [],
    }));
    mockGetSession.mockImplementation(async (sessionId: string) => ({
      id: sessionId,
      created_at: "2026-01-01T00:00:00Z",
      last_active: "2026-01-01T00:00:00Z",
      metadata: {},
      document_ids: [],
    }));

    const { result, rerender } = renderHook(
      ({ sessionId }) => useChat(sessionId, DEFAULT_RETRIEVAL_SETTINGS),
      { initialProps: { sessionId: "session-a" } },
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
      result.current.setInput("Question");
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    await act(async () => {
      void result.current.handleSend();
    });

    rerender({ sessionId: "session-b" });

    await waitFor(() =>
      expect(result.current.messages.some((m) => m.text === "History for B")).toBe(
        true,
      ),
    );

    act(() => {
      releaseStream?.();
    });

    await waitFor(() => expect(result.current.inflight).toBe(false));
    expect(result.current.messages.some((m) => m.text.includes("stale"))).toBe(
      false,
    );
  });

  it("attaches retrieval_debug from stream complete _raw", async () => {
    mockSendMessageStream.mockImplementation(async function* () {
      yield {
        type: "complete",
        sources: [{ file_name: "a.pdf", page_number: 1, chunk_index: 0, score: 0.9 }],
        latency_ms: 120,
        model: "m",
        _raw: {
          retrieval_debug: { original_query: "What is RAG?" },
        },
      };
    });

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
      result.current.setInput("What is RAG?");
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    await act(async () => {
      await result.current.handleSend();
    });

    await waitFor(() =>
      expect(
        result.current.messages.some(
          (m) => m.retrieval_debug?.original_query === "What is RAG?",
        ),
      ).toBe(true),
    );
  });

  it("ignores sync fallback answer after session switch and keeps B history", async () => {
    let resolveSend:
      | ((value: {
          answer: string;
          question: string;
          chunks: number;
          sources: [];
          model: string;
        }) => void)
      | undefined;

    mockSendMessageStream.mockImplementation(async function* () {
      throw new StreamingDisabledError();
    });

    mockSendMessage.mockImplementation((_question, _docId, options) => {
      return new Promise((resolve, reject) => {
        const onAbort = () => {
          reject(new DOMException("Aborted", "AbortError"));
        };
        options?.signal?.addEventListener("abort", onAbort, { once: true });
        resolveSend = resolve;
      });
    });

    mockGetSessionHistory.mockImplementation(async (sessionId: string) => ({
      messages:
        sessionId === "session-b"
          ? [{ id: "m-1", role: "assistant", content: "History for B" }]
          : [],
    }));
    mockGetSession.mockImplementation(async (sessionId: string) => ({
      id: sessionId,
      created_at: "2026-01-01T00:00:00Z",
      last_active: "2026-01-01T00:00:00Z",
      metadata: {},
      document_ids: [],
    }));

    const { result, rerender } = renderHook(
      ({ sessionId }) => useChat(sessionId, DEFAULT_RETRIEVAL_SETTINGS),
      { initialProps: { sessionId: "session-a" } },
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
      result.current.setInput("Question");
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    await act(async () => {
      void result.current.handleSend();
    });

    rerender({ sessionId: "session-b" });

    await waitFor(() =>
      expect(result.current.messages.some((m) => m.text === "History for B")).toBe(
        true,
      ),
    );

    await act(async () => {
      resolveSend?.({
        answer: "Stale sync answer",
        question: "Question",
        chunks: 1,
        sources: [],
        model: "m",
      });
    });

    await waitFor(() => expect(result.current.inflight).toBe(false));
    expect(
      result.current.messages.some((m) => m.text === "Stale sync answer"),
    ).toBe(false);
    expect(
      result.current.messages.some((m) =>
        m.text.includes("Something went wrong"),
      ),
    ).toBe(false);
    expect(mockSendMessage).toHaveBeenCalledWith(
      "Question",
      "doc-1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("does not apply buffered tokens from session A after switching to session B", async () => {
    let rafCallback: FrameRequestCallback | null = null;
    const rafSpy = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((callback) => {
        rafCallback = callback;
        return 1;
      });
    const cancelSpy = vi
      .spyOn(window, "cancelAnimationFrame")
      .mockImplementation(() => {});

    let releaseFirstStream: (() => void) | undefined;
    const firstStreamGate = new Promise<void>((resolve) => {
      releaseFirstStream = resolve;
    });

    mockSendMessageStream
      .mockImplementationOnce(async function* () {
        await firstStreamGate;
        yield { type: "token", text: "stale-buffer" };
      })
      .mockImplementationOnce(async function* () {
        yield { type: "token", text: "fresh" };
        yield {
          type: "complete",
          sources: [],
          latency_ms: 1,
          model: "m",
          _raw: {},
        };
      });

    mockGetSessionHistory.mockImplementation(async (sessionId: string) => ({
      messages:
        sessionId === "session-b"
          ? [{ id: "m-1", role: "assistant", content: "History for B" }]
          : [],
    }));
    mockGetSession.mockImplementation(async (sessionId: string) => ({
      id: sessionId,
      created_at: "2026-01-01T00:00:00Z",
      last_active: "2026-01-01T00:00:00Z",
      metadata: {},
      document_ids: [],
    }));

    const { result, rerender } = renderHook(
      ({ sessionId }) => useChat(sessionId, DEFAULT_RETRIEVAL_SETTINGS),
      { initialProps: { sessionId: "session-a" } },
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
      result.current.setInput("Question A");
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    await act(async () => {
      void result.current.handleSend();
    });

    await act(async () => {
      releaseFirstStream?.();
    });

    await waitFor(() => expect(rafCallback).not.toBeNull());

    rerender({ sessionId: "session-b" });

    await waitFor(() =>
      expect(result.current.messages.some((m) => m.text === "History for B")).toBe(
        true,
      ),
    );

    act(() => {
      rafCallback?.(0);
    });

    expect(
      result.current.messages.some((m) => m.text.includes("stale-buffer")),
    ).toBe(false);

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
      result.current.setInput("Question B");
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    await act(async () => {
      await result.current.handleSend();
    });

    await waitFor(() =>
      expect(result.current.messages.some((m) => m.text.includes("fresh"))).toBe(
        true,
      ),
    );
    expect(
      result.current.messages.some((m) => m.text.includes("stale-buffer")),
    ).toBe(false);

    rafSpy.mockRestore();
    cancelSpy.mockRestore();
  });

  it("restores the status file name when localStorage has no entry", async () => {
    const documentId = "0a22a97f-1111-4111-8111-111111111111";
    mockGetSession.mockResolvedValue(sessionPayload("session-a", [documentId]));
    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      file_name: "notes.txt",
    });
    mockGetUploadedDocument.mockReturnValue(undefined);

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.attachment?.status).toBe("ready"));

    expect(result.current.attachment).toMatchObject({
      documentId,
      fileName: "notes.txt",
      status: "ready",
    });
    expect(result.current.attachment?.fileName).not.toBe(
      `Document ${documentId.slice(0, 8)}`,
    );
    expect(mockGetUploadedDocument).toHaveBeenCalledWith(documentId);
  });

  it.each([
    ["processing", "embedding", "processing"],
    ["failed", "failed", "failed"],
  ] as const)(
    "restores a %s document name from status when localStorage is empty",
    async (_label, apiStatus, attachmentStatus) => {
      mockPoll.status = attachmentStatus;
      mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-notes"]));
      mockGetDocumentStatus.mockResolvedValue({
        status: apiStatus,
        file_name: "notes.txt",
      });
      mockGetUploadedDocument.mockReturnValue(undefined);

      const { result } = renderHook(() =>
        useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
      );

      await waitFor(() =>
        expect(result.current.attachment?.status).toBe(attachmentStatus),
      );
      expect(result.current.attachment?.fileName).toBe("notes.txt");
    },
  );

  it("prefers the status file name over a conflicting localStorage name", async () => {
    mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-1"]));
    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      file_name: "notes.txt",
    });
    mockGetUploadedDocument.mockReturnValue({
      documentId: "doc-1",
      fileName: "stale.pdf",
      uploadedAt: 1,
    });

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.attachment?.fileName).toBe("notes.txt"));
    expect(result.current.attachment?.fileName).not.toBe("stale.pdf");
  });

  it("uses the status file name after upload once polling has read it", async () => {
    mockPoll.status = "processing";
    mockPoll.fileName = undefined;

    const { result, rerender } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "selected.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
    });

    expect(result.current.attachment).toMatchObject({
      fileName: "selected.pdf",
      status: "processing",
    });

    mockPoll.fileName = "notes.txt";
    rerender();

    await waitFor(() =>
      expect(result.current.attachment).toMatchObject({
        fileName: "notes.txt",
        status: "processing",
      }),
    );
  });

  it("restores a missing document as an empty attachment and keeps history", async () => {
    mockGetSessionHistory.mockResolvedValue({
      messages: [
        { id: "m-1", role: "user", content: "Where is the appendix?" },
        { id: "m-2", role: "assistant", content: "Page 4." },
      ],
    });
    mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-missing"]));
    mockGetDocumentStatus.mockRejectedValue(new DocumentNotFoundError("missing"));

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    expect(result.current.attachment).toBeNull();
    expect(result.current.sessionNotice).toBe(DOCUMENT_GONE_NOTICE);
    expect(result.current.messages.map((message) => message.text)).toEqual([
      "Where is the appendix?",
      "Page 4.",
    ]);
    expect(result.current.messages.some((message) => message.text === WELCOME_TEXT)).toBe(
      false,
    );
    expect(result.current.inflight).toBe(false);
    expect(mockGetDocumentStatus).toHaveBeenCalledWith("/documents/doc-missing/status");
  });

  it("restores assistant citation snapshots without model, latency, or debug data", async () => {
    mockGetSessionHistory.mockResolvedValue({
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "What is the limit?",
          sources: [
            {
              file_name: "should-not-cite-user.pdf",
              page_number: 1,
              chunk_index: 0,
              score: 0.2,
            },
          ],
        },
        {
          id: "asst-1",
          role: "assistant",
          content: "Ten days.",
          sources: [
            {
              file_name: "handbook-v1.pdf",
              page_number: 3,
              page_end: 5,
              chunk_index: 2,
              score: 0.91,
              score_type: "vector",
            },
          ],
          model: "gpt-test",
          latency_ms: 1200,
          retrieval_debug: { original_query: "What is the limit?" },
          chunks: 4,
          question: "What is the limit?",
        },
        {
          id: "asst-empty",
          role: "assistant",
          content: "Nothing cited.",
          sources: [],
        },
        {
          id: "asst-null",
          role: "assistant",
          content: "Older answer.",
          sources: null,
        },
        {
          id: "asst-missing",
          role: "assistant",
          content: "Pre-snapshot answer.",
        },
      ],
    });
    mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-1"]));
    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      file_name: "handbook-v2.pdf",
    });

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    const [user, cited, empty, missingNull, missingField] = result.current.messages;

    expect(user).toMatchObject({
      id: 1,
      historyId: "user-1",
      sender: "user",
      text: "What is the limit?",
    });
    expect(user.sources).toBeUndefined();

    expect(cited).toMatchObject({
      id: 2,
      historyId: "asst-1",
      sender: "ai",
      text: "Ten days.",
      sources: [
        {
          file_name: "handbook-v1.pdf",
          page_number: 3,
          page_end: 5,
          chunk_index: 2,
          score: 0.91,
          score_type: "vector",
        },
      ],
    });
    expect(cited.model).toBeUndefined();
    expect(cited.latency_ms).toBeUndefined();
    expect(cited.retrieval_debug).toBeUndefined();
    expect(cited.chunks).toBeUndefined();
    expect(cited.question).toBeUndefined();
    expect(cited.sources?.[0].file_name).toBe("handbook-v1.pdf");
    expect(cited.sources?.[0].page_end).toBe(5);

    expect(empty.historyId).toBe("asst-empty");
    expect(empty.sources).toBeUndefined();
    expect(missingNull.historyId).toBe("asst-null");
    expect(missingNull.sources).toBeUndefined();
    expect(missingField.historyId).toBe("asst-missing");
    expect(missingField.sources).toBeUndefined();

    expect(result.current.attachment?.fileName).toBe("handbook-v2.pdf");
  });

  it("shows the other session's snapshot after a switch", async () => {
    mockGetSessionHistory.mockImplementation(async (sessionId: string) => ({
      messages:
        sessionId === "session-b"
          ? [
              {
                id: "asst-b",
                role: "assistant",
                content: "See the notes.",
                sources: [{ file_name: "notes.txt", chunk_index: 0, score: 0.4 }],
              },
            ]
          : [
              {
                id: "asst-a",
                role: "assistant",
                content: "See the handbook.",
                sources: [
                  {
                    file_name: "handbook-v1.pdf",
                    page_number: 3,
                    chunk_index: 2,
                    score: 0.91,
                  },
                ],
              },
            ],
    }));
    mockGetSession.mockImplementation(async (sessionId: string) =>
      sessionPayload(sessionId),
    );

    const { result, rerender } = renderHook(
      ({ sessionId }) => useChat(sessionId, DEFAULT_RETRIEVAL_SETTINGS),
      { initialProps: { sessionId: "session-a" } },
    );

    await waitFor(() =>
      expect(result.current.messages[0]?.sources?.[0]?.file_name).toBe(
        "handbook-v1.pdf",
      ),
    );

    rerender({ sessionId: "session-b" });

    await waitFor(() =>
      expect(result.current.messages[0]?.historyId).toBe("asst-b"),
    );
    expect(result.current.messages[0]?.sources?.[0]?.file_name).toBe("notes.txt");
    expect(
      result.current.messages.some((message) =>
        message.sources?.some((source) => source.file_name === "handbook-v1.pdf"),
      ),
    ).toBe(false);
  });

  it.each([
    ["non-404 status error", new Error("Status check failed: 500")],
    ["network error", new TypeError("Failed to fetch")],
  ])(
    "restores an unfetchable document (%s) without the opaque restore sentence",
    async (_label, error) => {
      mockGetSessionHistory.mockResolvedValue({
        messages: [{ id: "m-1", role: "user", content: "Earlier question" }],
      });
      mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-down"]));
      mockGetDocumentStatus.mockRejectedValue(error);

      const { result } = renderHook(() =>
        useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
      );

      await waitFor(() => expect(result.current.historyLoading).toBe(false));

      expect(result.current.attachment).toBeNull();
      expect(result.current.sessionNotice).toBe(DOCUMENT_UNAVAILABLE_NOTICE);
      expect(result.current.sessionNotice).not.toBe(OPAQUE_RESTORE_NOTICE);
      expect(result.current.messages.map((message) => message.text)).toEqual([
        "Earlier question",
      ]);
      expect(result.current.inflight).toBe(false);
    },
  );

  it("keeps a failed document attached and does not explain it only after send", async () => {
    mockGetSessionHistory.mockResolvedValue({
      messages: [{ id: "m-1", role: "assistant", content: "Earlier answer" }],
    });
    mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-failed"]));
    mockGetDocumentStatus.mockResolvedValue({ status: "failed" });
    mockGetUploadedDocument.mockReturnValue({
      documentId: "doc-failed",
      fileName: "broken.pdf",
      uploadedAt: 1,
    });

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.attachment?.status).toBe("failed"));

    expect(result.current.attachment).toMatchObject({
      documentId: "doc-failed",
      fileName: "broken.pdf",
      status: "failed",
    });
    expect(result.current.sessionNotice).toBeNull();
    expect(result.current.messages.map((message) => message.text)).toEqual([
      "Earlier answer",
    ]);
    expect(
      result.current.messages.some((message) =>
        message.text.includes("Document processing failed"),
      ),
    ).toBe(false);
    expect(mockSendMessageStream).not.toHaveBeenCalled();

    act(() => {
      result.current.setInput("Try anyway");
    });
    await act(async () => {
      await result.current.handleSend();
    });

    expect(result.current.attachment?.status).toBe("failed");
    expect(
      result.current.messages.some(
        (message) =>
          message.text ===
          "Document processing failed. Please remove it and upload again.",
      ),
    ).toBe(true);
  });

  it("restores a replaced document that status still reports as completed", async () => {
    mockGetSession.mockResolvedValue(
      sessionPayload("session-a", ["doc-previous", "doc-same"]),
    );
    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      status_detail: "replacing",
    });
    mockGetUploadedDocument.mockImplementation((documentId: string) =>
      documentId === "doc-same"
        ? { documentId, fileName: "current.pdf", uploadedAt: 1 }
        : undefined,
    );

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.attachment?.status).toBe("ready"));

    expect(result.current.attachment).toMatchObject({
      documentId: "doc-same",
      fileName: "current.pdf",
      status: "ready",
    });
    expect(result.current.sessionNotice).toBeNull();
    expect(mockGetDocumentStatus).toHaveBeenCalledTimes(1);
    expect(mockGetDocumentStatus).toHaveBeenCalledWith("/documents/doc-same/status");
  });

  it("shows a notice when session history cannot be loaded", async () => {
    mockGetSessionHistory.mockRejectedValue(new Error("history failed"));
    mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-1"]));

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    expect(result.current.sessionNotice).toBe(SESSION_HISTORY_FAILED_NOTICE);
    expect(result.current.messages.map((message) => message.text)).toEqual([WELCOME_TEXT]);
    expect(result.current.attachment).toBeNull();
    expect(result.current.inflight).toBe(false);
    expect(mockGetDocumentStatus).not.toHaveBeenCalled();

    act(() => {
      result.current.setInput("Continue");
    });
    expect(result.current.sendDisabled).toBe(false);
  });

  it("keeps loaded history and shows a notice when the session cannot be loaded", async () => {
    mockGetSessionHistory.mockResolvedValue({
      messages: [{ id: "m-1", role: "user", content: "Saved question" }],
    });
    mockGetSession.mockRejectedValue(new Error("session failed"));

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    expect(result.current.sessionNotice).toBe(SESSION_DETAILS_FAILED_NOTICE);
    expect(result.current.messages.map((message) => message.text)).toEqual([
      "Saved question",
    ]);
    expect(result.current.messages.some((message) => message.text === WELCOME_TEXT)).toBe(
      false,
    );
    expect(result.current.attachment).toBeNull();
    expect(result.current.inflight).toBe(false);
    expect(mockGetDocumentStatus).not.toHaveBeenCalled();

    act(() => {
      result.current.setInput("Continue");
    });
    expect(result.current.sendDisabled).toBe(false);
  });

  it("restores the stored session on load and the next session on switch", async () => {
    mockGetSessionHistory.mockImplementation(async (sessionId: string) => ({
      messages:
        sessionId === "session-b"
          ? [{ id: "b", role: "assistant", content: "History for B" }]
          : [{ id: "a", role: "user", content: "History for A" }],
    }));
    mockGetSession.mockImplementation(async (sessionId: string) =>
      sessionPayload(sessionId, sessionId === "session-b" ? ["doc-b"] : ["doc-a"]),
    );
    mockGetDocumentStatus.mockResolvedValue({ status: "completed" });
    mockGetUploadedDocument.mockImplementation((documentId: string) => ({
      documentId,
      fileName: documentId === "doc-b" ? "notes.pdf" : "report.pdf",
      uploadedAt: 1,
    }));

    const { result, rerender } = renderHook(
      ({ sessionId }) => useChat(sessionId, DEFAULT_RETRIEVAL_SETTINGS),
      { initialProps: { sessionId: "session-a" } },
    );

    await waitFor(() =>
      expect(result.current.attachment).toMatchObject({
        documentId: "doc-a",
        fileName: "report.pdf",
        status: "ready",
      }),
    );
    expect(result.current.messages.map((message) => message.text)).toEqual([
      "History for A",
    ]);
    expect(result.current.sessionNotice).toBeNull();

    rerender({ sessionId: "session-b" });

    await waitFor(() =>
      expect(result.current.attachment).toMatchObject({
        documentId: "doc-b",
        fileName: "notes.pdf",
        status: "ready",
      }),
    );
    expect(result.current.messages.map((message) => message.text)).toEqual([
      "History for B",
    ]);
    expect(result.current.sessionNotice).toBeNull();
    expect(result.current.inflight).toBe(false);
    expect(result.current.historyLoading).toBe(false);
    expect(mockGetDocumentStatus).toHaveBeenCalledWith("/documents/doc-a/status");
    expect(mockGetDocumentStatus).toHaveBeenCalledWith("/documents/doc-b/status");
  });

  it("keeps stop and an in-flight session switch from showing a restore error", async () => {
    mockSendMessageStream.mockImplementation(async function* (
      _text: string,
      _documentId: string,
      options: { signal?: AbortSignal },
    ) {
      const signal = options?.signal;
      await new Promise<void>((_resolve, reject) => {
        const onAbort = () => reject(new DOMException("Aborted", "AbortError"));
        if (signal?.aborted) {
          onAbort();
          return;
        }
        signal?.addEventListener("abort", onAbort, { once: true });
      });
      yield { type: "token" as const, text: "partial" };
    });

    mockGetSessionHistory.mockImplementation(async (sessionId: string) => ({
      messages:
        sessionId === "session-b"
          ? [{ id: "b", role: "assistant", content: "History for B" }]
          : [],
    }));
    mockGetSession.mockImplementation(async (sessionId: string) =>
      sessionPayload(sessionId, sessionId === "session-b" ? ["doc-b"] : ["doc-a"]),
    );
    mockGetDocumentStatus.mockResolvedValue({ status: "completed" });
    mockGetUploadedDocument.mockImplementation((documentId: string) => ({
      documentId,
      fileName: documentId === "doc-b" ? "notes.pdf" : "report.pdf",
      uploadedAt: 1,
    }));

    const { result, rerender } = renderHook(
      ({ sessionId }) => useChat(sessionId, DEFAULT_RETRIEVAL_SETTINGS),
      { initialProps: { sessionId: "session-a" } },
    );

    await waitFor(() =>
      expect(result.current.attachment).toMatchObject({
        documentId: "doc-a",
        status: "ready",
      }),
    );

    act(() => {
      result.current.setInput("Question");
    });
    await act(async () => {
      void result.current.handleSend();
    });
    await waitFor(() => expect(result.current.streaming).toBe(true));

    await act(async () => {
      result.current.stopStreaming();
    });

    await waitFor(() => expect(result.current.inflight).toBe(false));
    expect(result.current.streaming).toBe(false);
    expect(result.current.sessionNotice).toBeNull();
    expect(
      result.current.messages.some((message) =>
        message.text.includes("Could not restore"),
      ),
    ).toBe(false);

    act(() => {
      result.current.setInput("Still here");
    });
    expect(result.current.sendDisabled).toBe(false);

    await act(async () => {
      void result.current.handleSend();
    });
    await waitFor(() => expect(result.current.streaming).toBe(true));

    rerender({ sessionId: "session-b" });

    await waitFor(() =>
      expect(result.current.attachment).toMatchObject({
        documentId: "doc-b",
        fileName: "notes.pdf",
        status: "ready",
      }),
    );
    expect(result.current.messages.map((message) => message.text)).toEqual([
      "History for B",
    ]);
    expect(result.current.sessionNotice).toBeNull();
    expect(result.current.inflight).toBe(false);
    expect(result.current.streaming).toBe(false);
    expect(result.current.historyLoading).toBe(false);
    expect(
      result.current.messages.some((message) => message.text.includes("partial")),
    ).toBe(false);

    act(() => {
      result.current.setInput("Ask B");
    });
    expect(result.current.sendDisabled).toBe(false);
  });

  it("reports the first useful question and attached file name, and ignores a later question", async () => {
    mockSendMessageStream.mockImplementation(async function* () {
      yield { type: "token", text: "Answer" };
      yield { type: "complete", sources: [], latency_ms: 1, model: "m", _raw: {} };
    });
    const onUserQuestion = vi.fn();
    const onDocumentAttached = vi.fn();
    const onHistoryLoaded = vi.fn();

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS, {
        onUserQuestion,
        onDocumentAttached,
        onHistoryLoaded,
      }),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));
    expect(onHistoryLoaded).toHaveBeenCalledWith("session-a", false);

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "  notes.txt  ",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
    });
    expect(onDocumentAttached).toHaveBeenCalledWith("session-a", "notes.txt");

    await waitFor(() => expect(result.current.attachment?.status).toBe("ready"));

    act(() => {
      result.current.setInput("Who\napproves   expenses?");
    });
    await act(async () => {
      await result.current.handleSend();
    });
    expect(onUserQuestion).toHaveBeenCalledTimes(1);
    expect(onUserQuestion).toHaveBeenCalledWith("session-a", "Who\napproves   expenses?");

    act(() => {
      result.current.setInput("What about travel?");
    });
    await act(async () => {
      await result.current.handleSend();
    });
    expect(onUserQuestion).toHaveBeenCalledTimes(1);
    expect(onDocumentAttached).toHaveBeenCalledTimes(1);
  });

  it("replaces an existing attachment in place with the same documentId without calling deleteDocument or removeUploadedDocument", async () => {
    const { deleteDocument } = await import("../api");
    const { removeUploadedDocument, saveUploadedDocument } = await import(
      "../documentStore"
    );
    vi.mocked(deleteDocument).mockClear();
    vi.mocked(removeUploadedDocument).mockClear();
    vi.mocked(saveUploadedDocument).mockClear();

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "first.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
    });

    expect(deleteDocument).not.toHaveBeenCalled();
    expect(removeUploadedDocument).not.toHaveBeenCalled();
    expect(saveUploadedDocument).toHaveBeenCalledWith({
      documentId: "doc-1",
      fileName: "first.pdf",
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "second.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
    });

    expect(deleteDocument).not.toHaveBeenCalled();
    expect(removeUploadedDocument).not.toHaveBeenCalled();
    expect(saveUploadedDocument).toHaveBeenLastCalledWith({
      documentId: "doc-1",
      fileName: "second.pdf",
    });
    expect(result.current.attachment?.documentId).toBe("doc-1");
    expect(result.current.attachment?.fileName).toBe("second.pdf");

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );
    expect(
      result.current.messages.some((m) =>
        m.text.includes('Document "second.pdf" is ready.'),
      ),
    ).toBe(true);
  });

  it("still calls deleteDocument and clears the chip on explicit handleRemoveAttachment", async () => {
    const { deleteDocument } = await import("../api");
    const { removeUploadedDocument } = await import("../documentStore");
    vi.mocked(deleteDocument).mockClear();
    vi.mocked(deleteDocument).mockResolvedValue({ status: "gone" });
    vi.mocked(removeUploadedDocument).mockClear();

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "first.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    await act(async () => {
      await result.current.handleRemoveAttachment();
    });

    expect(deleteDocument).toHaveBeenCalledWith("doc-1");
    expect(removeUploadedDocument).toHaveBeenCalledWith("doc-1");
    expect(result.current.attachment).toBeNull();
  });

  it("restores the previous ready attachment and surfaces the failure when an in-place replacement fails", async () => {
    const { saveUploadedDocument } = await import("../documentStore");
    vi.mocked(saveUploadedDocument).mockClear();

    const { result, rerender } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() => expect(result.current.historyLoading).toBe(false));

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "first.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
    });

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );

    mockPoll.status = "processing";
    mockPoll.stage = "queued";
    mockPoll.errorMessage = undefined;

    act(() => {
      result.current.handleUploadAccepted({
        fileName: "second.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
      });
    });

    expect(result.current.attachment?.status).toBe("processing");
    expect(result.current.attachment?.fileName).toBe("second.pdf");

    mockPoll.status = "failed";
    mockPoll.stage = "embedding";
    mockPoll.errorMessage = "Embedding provider exploded";
    mockPoll.apiStatus = "completed";
    mockPoll.statusDetail = "replacement_failed";
    rerender();

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );
    expect(result.current.attachment?.documentId).toBe("doc-1");
    expect(result.current.attachment?.fileName).toBe("first.pdf");
    expect(result.current.removeError).toBe("Embedding provider exploded");
    expect(saveUploadedDocument).toHaveBeenLastCalledWith({
      documentId: "doc-1",
      fileName: "first.pdf",
    });
  });

  it("keeps the previous completed document usable when replacement fails after a remount", async () => {
    const { saveUploadedDocument } = await import("../documentStore");
    vi.mocked(saveUploadedDocument).mockClear();
    mockSendMessageStream.mockImplementation(async function* () {
      yield {
        type: "complete",
        sources: [],
        latency_ms: 10,
        model: "m",
        _raw: {},
      };
    });

    mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-1"]));
    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      status_detail: "replacement_in_progress",
      file_name: "first.pdf",
    });
    mockPoll.status = "processing";
    mockPoll.stage = "queued";
    mockPoll.fileName = "first.pdf";
    mockPoll.apiStatus = "completed";
    mockPoll.statusDetail = "replacement_in_progress";

    const { result, rerender } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("processing"),
    );
    expect(result.current.attachment).toMatchObject({
      documentId: "doc-1",
      fileName: "first.pdf",
    });
    expect(result.current.removeError).toBeNull();

    mockPoll.status = "failed";
    mockPoll.stage = "embedding";
    mockPoll.errorMessage = "Embedding provider exploded";
    mockPoll.apiStatus = "completed";
    mockPoll.statusDetail = "replacement_failed";
    mockPoll.fileName = "first.pdf";
    rerender();

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );
    expect(result.current.attachment?.fileName).toBe("first.pdf");
    expect(result.current.removeError).toBe("Embedding provider exploded");
    expect(saveUploadedDocument).toHaveBeenCalledWith({
      documentId: "doc-1",
      fileName: "first.pdf",
    });

    act(() => {
      result.current.setInput("What does the original say?");
    });
    await act(async () => {
      await result.current.handleSend();
    });

    expect(
      result.current.messages.some((message) =>
        message.text.includes("Please remove it and upload again."),
      ),
    ).toBe(false);
    expect(mockSendMessageStream).toHaveBeenCalledWith(
      "What does the original say?",
      "doc-1",
      expect.anything(),
      expect.anything(),
    );
  });

  it("restores a completed document and shows the error when a failed replacement is already on the session", async () => {
    mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-1"]));
    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      status_detail: "replacement_failed",
      file_name: "first.pdf",
      error: { message: "Embedding provider exploded" },
    });

    const { result } = renderHook(() =>
      useChat("session-a", DEFAULT_RETRIEVAL_SETTINGS),
    );

    await waitFor(() =>
      expect(result.current.attachment?.status).toBe("ready"),
    );
    expect(result.current.attachment).toMatchObject({
      documentId: "doc-1",
      fileName: "first.pdf",
      status: "ready",
    });
    expect(result.current.removeError).toBe("Embedding provider exploded");
  });
});

"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  deleteDocument,
  sendMessage,
  sendMessageStream,
  getSessionHistory,
  getSession,
  getDocumentStatus,
  DocumentNotFoundError,
  ChatError,
  StreamingDisabledError,
  type AttachmentState,
  type Message,
  type SessionHistoryMessage,
  type StreamEvent,
} from "../api";
import { useDocumentPolling } from "./useDocumentPolling";
import {
  saveUploadedDocument,
  removeUploadedDocument,
  getUploadedDocument,
} from "../documentStore";
import type { RetrievalSettings } from "../retrievalSettings";

const welcomeMessages: Message[] = [
  {
    id: 1,
    sender: "ai",
    text: "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it.",
  },
];

function mapHistoryToMessages(history: SessionHistoryMessage[]): Message[] {
  return history.map((entry, index) => ({
    id: index + 1,
    sender: entry.role === "user" ? "user" : "ai",
    text: entry.content,
  }));
}

function documentStatusEndpoint(documentId: string): string {
  return `/documents/${documentId}/status`;
}

function mapApiStatusToAttachmentStatus(
  apiStatus: string,
  statusDetail?: string
): AttachmentState["status"] {
  if (statusDetail === "replacement_in_progress") return "processing";
  if (apiStatus === "completed") return "ready";
  if (apiStatus === "failed") return "failed";
  return "processing";
}

function retrievalDebugFromCompleteRaw(
  raw: Record<string, unknown> | undefined,
): Message["retrieval_debug"] | undefined {
  const value = raw?.retrieval_debug;
  if (value != null && typeof value === "object" && !Array.isArray(value)) {
    return value as Message["retrieval_debug"];
  }
  return undefined;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function restoreSessionAttachment(
  documentId: string
): Promise<{ attachment: AttachmentState | null; notice: string | null }> {
  const statusEndpoint = documentStatusEndpoint(documentId);
  const stored = getUploadedDocument(documentId);
  const fileName = stored?.fileName ?? `Document ${documentId.slice(0, 8)}`;

  try {
    const status = await getDocumentStatus(statusEndpoint);
    return {
      attachment: {
        fileName,
        documentId,
        statusEndpoint,
        status: mapApiStatusToAttachmentStatus(
          status.status,
          status.status_detail
        ),
        ...(status.queue_position !== undefined
          ? { queue_position: status.queue_position }
          : {}),
      },
      notice: null,
    };
  } catch (error) {
    if (error instanceof DocumentNotFoundError) {
      return {
        attachment: null,
        notice: "The document attached to this session is no longer available.",
      };
    }
    return {
      attachment: null,
      notice: "Could not restore the session document. You can upload a new one.",
    };
  }
}

type ResetTurnMode = "stop" | "session" | "unmount";

export function useChat(sessionId: string | null, retrievalSettings: RetrievalSettings) {
  const [messages, setMessages] = useState<Message[]>(welcomeMessages);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [input, setInput] = useState("");
  const [attachment, setAttachment] = useState<AttachmentState | null>(null);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [inflight, setInflight] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const readyAnnouncedForDocRef = useRef<string | null>(null);
  const previousAttachmentRef = useRef<AttachmentState | null>(null);
  const historyRequestRef = useRef(0);
  const chatEpochRef = useRef(0);
  const inflightRef = useRef(false);
  const streamingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const pendingTokensRef = useRef<string>("");
  const rafIdRef = useRef<number | null>(null);
  const streamingMsgIdRef = useRef<number | null>(null);
  const tokenFlushEpochRef = useRef<number | null>(null);

  const resetTurn = useCallback((mode: ResetTurnMode) => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;

    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }

    if (mode === "stop" && streamingMsgIdRef.current !== null) {
      const msgId = streamingMsgIdRef.current;
      const remaining = pendingTokensRef.current;
      pendingTokensRef.current = "";
      tokenFlushEpochRef.current = null;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? { ...m, text: m.text + remaining, isStreaming: false }
            : m
        )
      );
      streamingMsgIdRef.current = null;
    } else {
      pendingTokensRef.current = "";
      streamingMsgIdRef.current = null;
      tokenFlushEpochRef.current = null;
    }

    inflightRef.current = false;
    streamingRef.current = false;

    if (mode !== "unmount") {
      setStreaming(false);
      setInflight(false);
    }
  }, []);

  const flushPendingTokens = useCallback(() => {
    rafIdRef.current = null;
    if (
      tokenFlushEpochRef.current === null ||
      tokenFlushEpochRef.current !== chatEpochRef.current
    ) {
      pendingTokensRef.current = "";
      return;
    }

    const tokens = pendingTokensRef.current;
    if (!tokens || streamingMsgIdRef.current === null) return;

    pendingTokensRef.current = "";
    const targetId = streamingMsgIdRef.current;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === targetId ? { ...m, text: m.text + tokens } : m
      )
    );
  }, []);

  const enqueueToken = useCallback(
    (text: string, epoch: number) => {
      pendingTokensRef.current += text;
      tokenFlushEpochRef.current = epoch;
      if (rafIdRef.current === null) {
        rafIdRef.current = requestAnimationFrame(flushPendingTokens);
      }
    },
    [flushPendingTokens]
  );

  // When session changes, reset local chat state and hydrate history from backend.
  useEffect(() => {
    if (!sessionId) return;

    const requestId = historyRequestRef.current + 1;
    historyRequestRef.current = requestId;
    chatEpochRef.current += 1;
    resetTurn("session");

    setInput("");
    setAttachment(null);
    setSessionNotice(null);
    setRemoveError(null);
    readyAnnouncedForDocRef.current = null;
    previousAttachmentRef.current = null;

    setHistoryLoading(true);
    setMessages([]);

    void (async () => {
      try {
        const [historyResult, sessionResult] = await Promise.all([
          getSessionHistory(sessionId),
          getSession(sessionId),
        ]);
        if (historyRequestRef.current !== requestId) return;

        setMessages(
          historyResult.messages.length > 0
            ? mapHistoryToMessages(historyResult.messages)
            : welcomeMessages
        );

        const documentIds = sessionResult.document_ids;
        if (documentIds.length === 0) return;

        const documentId = documentIds[documentIds.length - 1];
        const restored = await restoreSessionAttachment(documentId);
        if (historyRequestRef.current !== requestId) return;

        if (restored.attachment) {
          setAttachment(restored.attachment);
          setSessionNotice(null);
        } else if (restored.notice) {
          setAttachment(null);
          setSessionNotice(restored.notice);
        }
      } catch {
        if (historyRequestRef.current !== requestId) return;
        setMessages(welcomeMessages);
      } finally {
        if (historyRequestRef.current === requestId) {
          setHistoryLoading(false);
        }
      }
    })();
  }, [sessionId, resetTurn]);

  const poll = useDocumentPolling(
    attachment?.documentId,
    attachment?.statusEndpoint,
    attachment?.status
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, inflight]);

  useEffect(() => {
    readyAnnouncedForDocRef.current = null;
  }, [attachment?.documentId]);

  useEffect(() => {
    if (poll.status !== "ready" || !attachment || attachment.status !== "processing") {
      return;
    }
    const docId = attachment.documentId;
    if (readyAnnouncedForDocRef.current === docId) {
      return;
    }
    readyAnnouncedForDocRef.current = docId;
    previousAttachmentRef.current = null;
    const name = attachment.fileName;
    setAttachment((curr) => {
      if (!curr || curr.documentId !== docId || curr.status !== "processing") {
        return curr;
      }
      return {
        ...curr,
        status: "ready",
        stage: "completed",
        chunks: poll.chunks,
        processingTime: poll.processingTime,
      };
    });
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now(),
        sender: "ai",
        text: `Document "${name}" is ready. You can ask questions about it.`,
      },
    ]);
  }, [poll.status, poll.chunks, poll.processingTime, attachment]);

  useEffect(() => {
    if (poll.status !== "failed" || !attachment || attachment.status !== "processing") {
      return;
    }
    const docId = attachment.documentId;
    const previous =
      previousAttachmentRef.current?.documentId === docId
        ? previousAttachmentRef.current
        : null;
    previousAttachmentRef.current = null;

    if (previous) {
      saveUploadedDocument({
        documentId: previous.documentId,
        fileName: previous.fileName,
      });
      setAttachment(
        previous.status === "ready"
          ? previous
          : { ...previous, status: "failed" }
      );
      setRemoveError(poll.errorMessage ?? "Document replacement failed.");
      return;
    }

    setAttachment((curr) =>
      curr?.documentId === docId ? { ...curr, status: "failed" } : curr
    );
  }, [poll.status, poll.errorMessage, attachment]);

  useEffect(() => {
    return () => {
      resetTurn("unmount");
    };
  }, [resetTurn]);

  const consumeStream = useCallback(
    async (
      generator: AsyncGenerator<StreamEvent>,
      msgId: number,
      epoch: number,
    ) => {
      streamingMsgIdRef.current = msgId;
      let receivedComplete = false;

      for await (const event of generator) {
        if (chatEpochRef.current !== epoch) return;

        switch (event.type) {
          case "token":
            enqueueToken(event.text, epoch);
            break;

          case "complete": {
            const retrievalDebug = retrievalDebugFromCompleteRaw(event._raw);
            const completeMetadata = {
              sources: event.sources,
              latency_ms: event.latency_ms,
              model: event.model,
              isStreaming: false,
              ...(retrievalDebug !== undefined
                ? { retrieval_debug: retrievalDebug }
                : {}),
            };
            if (pendingTokensRef.current) {
              if (rafIdRef.current !== null) {
                cancelAnimationFrame(rafIdRef.current);
                rafIdRef.current = null;
              }
              const remaining = pendingTokensRef.current;
              pendingTokensRef.current = "";
              tokenFlushEpochRef.current = null;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId
                    ? { ...m, text: m.text + remaining, ...completeMetadata }
                    : m
                )
              );
            } else {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId ? { ...m, ...completeMetadata } : m
                )
              );
            }
            receivedComplete = true;
            break;
          }

          case "done":
            if (!receivedComplete) {
              if (pendingTokensRef.current) {
                if (rafIdRef.current !== null) {
                  cancelAnimationFrame(rafIdRef.current);
                  rafIdRef.current = null;
                }
                const remaining = pendingTokensRef.current;
                pendingTokensRef.current = "";
                tokenFlushEpochRef.current = null;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === msgId
                      ? { ...m, text: m.text + remaining, isStreaming: false }
                      : m
                  )
                );
              } else {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === msgId ? { ...m, isStreaming: false } : m
                  )
                );
              }
            }
            break;

          case "error":
            if (pendingTokensRef.current) {
              if (rafIdRef.current !== null) {
                cancelAnimationFrame(rafIdRef.current);
                rafIdRef.current = null;
              }
              const remaining = pendingTokensRef.current;
              pendingTokensRef.current = "";
              tokenFlushEpochRef.current = null;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId
                    ? {
                        ...m,
                        text: m.text + remaining,
                        isStreaming: false,
                        error: { code: event.code, message: event.message },
                      }
                    : m
                )
              );
            } else {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId
                    ? {
                        ...m,
                        isStreaming: false,
                        error: { code: event.code, message: event.message },
                      }
                    : m
                )
              );
            }
            break;
        }
      }

      streamingMsgIdRef.current = null;
    },
    [enqueueToken]
  );

  const stopStreaming = useCallback(() => {
    resetTurn("stop");
  }, [resetTurn]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || inflightRef.current) return;

    inflightRef.current = true;
    const epoch = chatEpochRef.current;

    setInput("");

    if (attachment === null) {
      const base = Date.now();
      setMessages((prev) => [
        ...prev,
        { id: base, sender: "user", text },
        {
          id: base + 1,
          sender: "ai",
          text: "Please upload a document first so I can answer questions about it.",
        },
      ]);
      inflightRef.current = false;
      return;
    }

    if (attachment.status === "processing") {
      const base = Date.now();
      setMessages((prev) => [
        ...prev,
        { id: base, sender: "user", text },
        {
          id: base + 1,
          sender: "ai",
          text: "Your document is still processing. Please wait a moment and try again.",
        },
      ]);
      inflightRef.current = false;
      return;
    }

    if (attachment.status === "failed") {
      const base = Date.now();
      setMessages((prev) => [
        ...prev,
        { id: base, sender: "user", text },
        {
          id: base + 1,
          sender: "ai",
          text: "Document processing failed. Please remove it and upload again.",
        },
      ]);
      inflightRef.current = false;
      return;
    }

    const base = Date.now();
    setMessages((prev) => [
      ...prev,
      { id: base, sender: "user", text, document_id: attachment.documentId },
    ]);
    setInflight(true);

    try {
      const controller = new AbortController();
      abortControllerRef.current = controller;

      const aiMsgId = base + 1;
      const chatOptions = {
        matchCount: retrievalSettings.matchCount,
        scope: retrievalSettings.scope,
        sessionId,
        signal: controller.signal,
      };

      setMessages((prev) => [
        ...prev,
        { id: aiMsgId, sender: "ai", text: "", isStreaming: true },
      ]);
      streamingRef.current = true;
      setStreaming(true);

      try {
        const generator = sendMessageStream(
          text,
          attachment.documentId,
          chatOptions,
          controller.signal,
        );
        await consumeStream(generator, aiMsgId, epoch);
      } catch (e) {
        if (chatEpochRef.current !== epoch) return;

        if (e instanceof StreamingDisabledError) {
          streamingRef.current = false;
          setStreaming(false);

          setMessages((prev) => prev.filter((m) => m.id !== aiMsgId));

          const response = await sendMessage(text, attachment.documentId, chatOptions);
          if (chatEpochRef.current !== epoch) return;

          setMessages((prev) => [
            ...prev,
            {
              id: aiMsgId,
              sender: "ai",
              text: response.answer,
              question: response.question,
              retrieval_debug: response.retrieval_debug,
              sources: response.sources,
              chunks: response.chunks,
              latency_ms: response.latency_ms,
              model: response.model,
              ...(response.status === "error"
                ? { error: response.error }
                : {}),
            },
          ]);
        } else if (isAbortError(e)) {
          // Stop/session/unmount already handled cleanup.
        } else {
          throw e;
        }
      }

      abortControllerRef.current = null;
    } catch (e) {
      if (chatEpochRef.current !== epoch) return;
      if (isAbortError(e)) return;

      let errorText = "Something went wrong. Please try again.";
      if (e instanceof ChatError) {
        errorText = e.message;
        if (e.code === "no_document") {
          setAttachment((curr) => (curr ? { ...curr, status: "failed" } : curr));
        }
      }
      setMessages((prev) => {
        const existing = prev.find((m) => m.id === base + 1);
        if (existing) {
          return prev.map((m) =>
            m.id === base + 1
              ? { ...m, text: m.text || errorText, isStreaming: false }
              : m
          );
        }
        return [...prev, { id: base + 1, sender: "ai" as const, text: errorText }];
      });
    } finally {
      if (chatEpochRef.current === epoch) {
        inflightRef.current = false;
        streamingRef.current = false;
        setInflight(false);
        setStreaming(false);
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    void handleSend();
  };

  const handleUploadAccepted = (payload: {
    fileName: string;
    documentId: string;
    statusEndpoint: string;
    queuePosition?: number;
  }) => {
    readyAnnouncedForDocRef.current = null;
    if (attachment && attachment.documentId === payload.documentId) {
      previousAttachmentRef.current = attachment;
    } else {
      previousAttachmentRef.current = null;
      if (attachment) {
        removeUploadedDocument(attachment.documentId);
      }
    }
    setRemoveError(null);
    setSessionNotice(null);
    saveUploadedDocument({
      documentId: payload.documentId,
      fileName: payload.fileName,
    });
    setAttachment({
      fileName: payload.fileName,
      documentId: payload.documentId,
      statusEndpoint: payload.statusEndpoint,
      status: "processing",
      queue_position: payload.queuePosition,
    });
  };

  const handleRemoveAttachment = async () => {
    if (!attachment) return;
    setRemoveError(null);
    try {
      const out = await deleteDocument(attachment.documentId);
      if (out.status === "gone") {
        previousAttachmentRef.current = null;
        removeUploadedDocument(attachment.documentId);
        setAttachment(null);
        return;
      }
      if (out.status === "conflict") {
        setRemoveError(out.message);
        return;
      }
      setRemoveError(out.message);
    } catch {
      setRemoveError("Could not remove the document. Try again.");
    }
  };

  const sendDisabled =
    inflight || !input.trim() || attachment?.status === "processing";

  return {
    messages,
    historyLoading,
    input,
    setInput,
    inflight,
    streaming,
    attachment,
    sessionNotice,
    removeError,
    sendDisabled,
    bottomRef,
    poll,
    handleSend,
    handleKeyDown,
    handleUploadAccepted,
    handleRemoveAttachment,
    stopStreaming,
  };
}

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
  parseRetrievalDebug,
} from "../api";
import { useDocumentPolling } from "./useDocumentPolling";
import {
  saveUploadedDocument,
  removeUploadedDocument,
  getUploadedDocument,
} from "../documentStore";
import type { DocumentScalarMetadata } from "../documentMetadata";
import type { AdvancedRetrievalState } from "../advancedRetrieval";

const welcomeMessages: Message[] = [
  {
    id: 1,
    sender: "ai",
    text: "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it.",
  },
];

const DOCUMENT_GONE_NOTICE =
  "The document attached to this session is no longer available. You can upload another.";
const DOCUMENT_UNAVAILABLE_NOTICE =
  "The document attached to this session could not be checked. You can upload another.";
const SESSION_HISTORY_FAILED_NOTICE =
  "This chat could not be loaded. You can upload a document and continue from here.";
const SESSION_DETAILS_FAILED_NOTICE =
  "This session could not be fully restored. You can upload a document to continue.";

function storedMessageId(value: string | undefined): string | undefined {
  if (typeof value !== "string" || value.trim() === "") return undefined;
  return value;
}

function mapHistoryToMessages(history: SessionHistoryMessage[]): Message[] {
  return history.map((entry, index) => {
    const sender = entry.role === "user" ? "user" : "ai";
    const sources =
      sender === "ai" && entry.sources && entry.sources.length > 0
        ? entry.sources
        : undefined;
    const messageId = storedMessageId(entry.id);
    return {
      id: index + 1,
      historyId: entry.id,
      ...(messageId ? { messageId } : {}),
      sender,
      text: entry.content,
      ...(sources ? { sources } : {}),
    };
  });
}

function documentStatusEndpoint(documentId: string): string {
  return `/documents/${documentId}/status`;
}

function mapApiStatusToAttachmentStatus(
  apiStatus: string,
  statusDetail?: string
): AttachmentState["status"] {
  if (statusDetail === "replacement_in_progress") return "processing";
  // A failed replacement leaves the previous completed content in place.
  if (statusDetail === "replacement_failed" && apiStatus === "completed") {
    return "ready";
  }
  if (apiStatus === "completed") return "ready";
  if (apiStatus === "failed") return "failed";
  return "processing";
}

function replacementFailureMessage(
  message: string | undefined
): string {
  const trimmed = message?.trim();
  return trimmed ? trimmed : "Document replacement failed.";
}

function retrievalDebugFromCompleteRaw(
  raw: Record<string, unknown> | undefined,
): Message["retrieval_debug"] | undefined {
  return parseRetrievalDebug(raw?.retrieval_debug);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function restoredAttachmentFileName(
  documentId: string,
  statusFileName: string | undefined,
  storedFileName: string | undefined,
): string {
  const fromStatus = statusFileName?.trim();
  if (fromStatus) return fromStatus;
  const fromStore = storedFileName?.trim();
  if (fromStore) return fromStore;
  return `Document ${documentId.slice(0, 8)}`;
}

async function restoreSessionAttachment(
  documentId: string
): Promise<{
  attachment: AttachmentState | null;
  notice: string | null;
  replacementError: string | null;
}> {
  const statusEndpoint = documentStatusEndpoint(documentId);
  const stored = getUploadedDocument(documentId);

  try {
    const status = await getDocumentStatus(statusEndpoint);
    return {
      attachment: {
        fileName: restoredAttachmentFileName(
          documentId,
          status.file_name,
          stored?.fileName,
        ),
        documentId,
        statusEndpoint,
        status: mapApiStatusToAttachmentStatus(
          status.status,
          status.status_detail
        ),
        ...(status.queue_position !== undefined
          ? { queue_position: status.queue_position }
          : {}),
        ...(status.metadata !== undefined ? { metadata: status.metadata } : {}),
      },
      notice: null,
      replacementError:
        status.status_detail === "replacement_failed"
          ? replacementFailureMessage(status.error?.message)
          : null,
    };
  } catch (error) {
    if (error instanceof DocumentNotFoundError) {
      return {
        attachment: null,
        notice: DOCUMENT_GONE_NOTICE,
        replacementError: null,
      };
    }
    return {
      attachment: null,
      notice: DOCUMENT_UNAVAILABLE_NOTICE,
      replacementError: null,
    };
  }
}

type ResetTurnMode = "stop" | "session" | "unmount";

export type ChatLabelEvents = {
  onUserQuestion?: (sessionId: string, text: string) => void;
  onDocumentAttached?: (sessionId: string, fileName: string) => void;
  onHistoryLoaded?: (sessionId: string, hasUsefulUserQuestion: boolean) => void;
};

function hasUsefulUserQuestion(messages: SessionHistoryMessage[]): boolean {
  return messages.some(
    (message) =>
      message.role === "user" && message.content.trim().replace(/\s+/g, " ").length > 0
  );
}

export function useChat(
  sessionId: string | null,
  advancedRetrieval: AdvancedRetrievalState,
  labelEvents?: ChatLabelEvents,
  inspectMode = false,
) {
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
  const labelEventsRef = useRef(labelEvents);
  labelEventsRef.current = labelEvents;
  const questionLockedRef = useRef(false);
  const historyReadyRef = useRef(false);
  const pendingQuestionRef = useRef<string | null>(null);
  const pendingFileRef = useRef<string | null>(null);

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
    questionLockedRef.current = false;
    historyReadyRef.current = false;
    pendingQuestionRef.current = null;
    pendingFileRef.current = null;
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
      const historyPromise = getSessionHistory(sessionId);
      const sessionPromise = getSession(sessionId);

      try {
        let historyResult: Awaited<ReturnType<typeof getSessionHistory>>;
        try {
          historyResult = await historyPromise;
        } catch {
          await sessionPromise.catch(() => undefined);
          if (historyRequestRef.current !== requestId) return;
          setMessages(welcomeMessages);
          setAttachment(null);
          setSessionNotice(SESSION_HISTORY_FAILED_NOTICE);
          return;
        }

        if (historyRequestRef.current !== requestId) {
          void sessionPromise.catch(() => undefined);
          return;
        }

        setMessages(
          historyResult.messages.length > 0
            ? mapHistoryToMessages(historyResult.messages)
            : welcomeMessages
        );

        historyReadyRef.current = true;
        const historyHasQuestion = hasUsefulUserQuestion(historyResult.messages);
        if (historyHasQuestion) {
          questionLockedRef.current = true;
          pendingQuestionRef.current = null;
          pendingFileRef.current = null;
          labelEventsRef.current?.onHistoryLoaded?.(sessionId, true);
        } else {
          labelEventsRef.current?.onHistoryLoaded?.(sessionId, false);
          const pendingQuestion = pendingQuestionRef.current;
          const pendingFile = pendingFileRef.current;
          pendingQuestionRef.current = null;
          pendingFileRef.current = null;
          if (pendingQuestion) {
            questionLockedRef.current = true;
            labelEventsRef.current?.onUserQuestion?.(sessionId, pendingQuestion);
          } else if (pendingFile) {
            labelEventsRef.current?.onDocumentAttached?.(sessionId, pendingFile);
          }
        }

        let sessionResult: Awaited<ReturnType<typeof getSession>>;
        try {
          sessionResult = await sessionPromise;
        } catch {
          if (historyRequestRef.current !== requestId) return;
          setAttachment(null);
          setSessionNotice(SESSION_DETAILS_FAILED_NOTICE);
          return;
        }

        if (historyRequestRef.current !== requestId) return;

        const documentIds = sessionResult.document_ids;
        if (documentIds.length === 0) return;

        const documentId = documentIds[documentIds.length - 1];
        try {
          const restored = await restoreSessionAttachment(documentId);
          if (historyRequestRef.current !== requestId) return;

          if (restored.attachment) {
            setAttachment(restored.attachment);
            setSessionNotice(null);
            if (restored.replacementError) {
              setRemoveError(restored.replacementError);
            }
          } else if (restored.notice) {
            setAttachment(null);
            setSessionNotice(restored.notice);
          }
        } catch {
          // A document-restore failure must not replace a transcript that already loaded.
          if (historyRequestRef.current !== requestId) return;
          setAttachment(null);
          setSessionNotice(DOCUMENT_UNAVAILABLE_NOTICE);
        }
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
    const statusName = poll.fileName?.trim();
    if (!statusName) return;
    setAttachment((curr) => {
      if (!curr || curr.fileName === statusName) return curr;
      return { ...curr, fileName: statusName };
    });
  }, [poll.fileName]);

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
    const statusName = poll.fileName?.trim();
    const name = statusName || attachment.fileName;
    setAttachment((curr) => {
      if (!curr || curr.documentId !== docId || curr.status !== "processing") {
        return curr;
      }
      return {
        ...curr,
        fileName: statusName || curr.fileName,
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
  }, [poll.status, poll.chunks, poll.processingTime, poll.fileName, attachment]);

  useEffect(() => {
    if (poll.status !== "failed" || !attachment || attachment.status !== "processing") {
      return;
    }
    const docId = attachment.documentId;
    const statusName = poll.fileName?.trim();
    const previous =
      previousAttachmentRef.current?.documentId === docId
        ? previousAttachmentRef.current
        : null;
    previousAttachmentRef.current = null;

    if (previous) {
      const fileName = statusName || previous.fileName;
      saveUploadedDocument({
        documentId: previous.documentId,
        fileName,
      });
      setAttachment(
        previous.status === "ready"
          ? { ...previous, fileName }
          : { ...previous, fileName, status: "failed" }
      );
      setRemoveError(replacementFailureMessage(poll.errorMessage));
      return;
    }

    // Remount drops the in-memory chip snapshot. The server still has the
    // previous completed content when status stays `completed`.
    if (
      poll.statusDetail === "replacement_failed" &&
      poll.apiStatus === "completed"
    ) {
      const fileName = statusName || attachment.fileName;
      saveUploadedDocument({ documentId: docId, fileName });
      setAttachment((curr) =>
        curr?.documentId === docId
          ? { ...curr, fileName, status: "ready", stage: "completed" }
          : curr
      );
      setRemoveError(replacementFailureMessage(poll.errorMessage));
      return;
    }

    if (poll.statusDetail === "replacement_failed") {
      setRemoveError(replacementFailureMessage(poll.errorMessage));
    }

    setAttachment((curr) =>
      curr?.documentId === docId
        ? { ...curr, fileName: statusName || curr.fileName, status: "failed" }
        : curr
    );
  }, [
    poll.status,
    poll.errorMessage,
    poll.fileName,
    poll.statusDetail,
    poll.apiStatus,
    attachment,
  ]);

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
            const messageId = storedMessageId(event.message_id);
            const completeMetadata = {
              sources: event.sources,
              latency_ms: event.latency_ms,
              model: event.model,
              isStreaming: false,
              ...(event.request_latency_ms !== undefined
                ? { request_latency_ms: event.request_latency_ms }
                : {}),
              ...(retrievalDebug !== undefined
                ? { retrieval_debug: retrievalDebug }
                : {}),
              ...(messageId ? { messageId } : {}),
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

    if (sessionId && !questionLockedRef.current) {
      if (!historyReadyRef.current) {
        pendingQuestionRef.current = text;
      } else {
        questionLockedRef.current = true;
        labelEventsRef.current?.onUserQuestion?.(sessionId, text);
      }
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
        retrieval: advancedRetrieval,
        sessionId,
        signal: controller.signal,
        ...(inspectMode ? { debugRetrieval: true } : {}),
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
              retrieval_debug: parseRetrievalDebug(response.retrieval_debug),
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
    metadata?: DocumentScalarMetadata;
  }) => {
    const fileName = payload.fileName.trim();
    if (sessionId && fileName && !questionLockedRef.current) {
      if (!historyReadyRef.current) {
        pendingFileRef.current = fileName;
      } else {
        labelEventsRef.current?.onDocumentAttached?.(sessionId, fileName);
      }
    }
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
      ...(payload.metadata !== undefined ? { metadata: payload.metadata } : {}),
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

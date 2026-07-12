"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  deleteDocument,
  sendMessage,
  sendMessageStream,
  ChatError,
  StreamingDisabledError,
  type AttachmentState,
  type Message,
  type StreamEvent,
} from "../api";
import { useDocumentPolling } from "./useDocumentPolling";
import {
  saveUploadedDocument,
  removeUploadedDocument,
} from "../documentStore";
import type { RetrievalSettings } from "../retrievalSettings";

const welcomeMessages: Message[] = [
  {
    id: 1,
    sender: "ai",
    text: "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it.",
  },
];

export function useChat(sessionId: string | null, retrievalSettings: RetrievalSettings) {
  const [messages, setMessages] = useState<Message[]>(welcomeMessages);
  const [input, setInput] = useState("");
  const [attachment, setAttachment] = useState<AttachmentState | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [inflight, setInflight] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const readyAnnouncedForDocRef = useRef<string | null>(null);

  // AbortController for cancelling an in-flight stream.
  const abortControllerRef = useRef<AbortController | null>(null);

  // Token batching: accumulate tokens between animation frames to avoid
  // excessive React re-renders when the LLM sends tokens very rapidly.
  const pendingTokensRef = useRef<string>("");
  const rafIdRef = useRef<number | null>(null);
  const streamingMsgIdRef = useRef<number | null>(null);

  // When session changes, reset the chat state.
  useEffect(() => {
    if (sessionId) {
      setMessages(welcomeMessages);
      setInput("");
      setAttachment(null);
      setRemoveError(null);
      setInflight(false);
      setStreaming(false);
      readyAnnouncedForDocRef.current = null;
      // Cancel any in-flight stream.
      abortControllerRef.current?.abort();
      abortControllerRef.current = null;
    }
  }, [sessionId]);

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
    setAttachment((curr) =>
      curr?.documentId === docId ? { ...curr, status: "failed" } : curr
    );
  }, [poll.status, attachment]);

  // ------------------------------------------------------------------
  // Token batching: flush accumulated tokens to the message via rAF
  // ------------------------------------------------------------------
  const flushPendingTokens = useCallback(() => {
    rafIdRef.current = null;
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
    (text: string) => {
      pendingTokensRef.current += text;
      if (rafIdRef.current === null) {
        rafIdRef.current = requestAnimationFrame(flushPendingTokens);
      }
    },
    [flushPendingTokens]
  );

  // Clean up rAF on unmount.
  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
    };
  }, []);

  // ------------------------------------------------------------------
  // Stream consumption
  // ------------------------------------------------------------------
  const consumeStream = useCallback(
    async (
      generator: AsyncGenerator<StreamEvent>,
      msgId: number,
    ) => {
      streamingMsgIdRef.current = msgId;
      let receivedComplete = false;

      for await (const event of generator) {
        switch (event.type) {
          case "token":
            enqueueToken(event.text);
            break;

          case "complete":
            // Flush any remaining buffered tokens before attaching metadata.
            if (pendingTokensRef.current) {
              if (rafIdRef.current !== null) {
                cancelAnimationFrame(rafIdRef.current);
                rafIdRef.current = null;
              }
              const remaining = pendingTokensRef.current;
              pendingTokensRef.current = "";
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === msgId
                    ? {
                        ...m,
                        text: m.text + remaining,
                        sources: event.sources,
                        latency_ms: event.latency_ms,
                        model: event.model,
                        isStreaming: false,
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
                        sources: event.sources,
                        latency_ms: event.latency_ms,
                        model: event.model,
                        isStreaming: false,
                      }
                    : m
                )
              );
            }
            receivedComplete = true;
            break;

          case "done":
            // Legacy completion marker. If we already got `complete`, this is
            // a no-op. Otherwise mark the message as finished.
            if (!receivedComplete) {
              // Flush remaining tokens
              if (pendingTokensRef.current) {
                if (rafIdRef.current !== null) {
                  cancelAnimationFrame(rafIdRef.current);
                  rafIdRef.current = null;
                }
                const remaining = pendingTokensRef.current;
                pendingTokensRef.current = "";
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
            // Flush remaining tokens, then mark error.
            if (pendingTokensRef.current) {
              if (rafIdRef.current !== null) {
                cancelAnimationFrame(rafIdRef.current);
                rafIdRef.current = null;
              }
              const remaining = pendingTokensRef.current;
              pendingTokensRef.current = "";
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

  // ------------------------------------------------------------------
  // Stop streaming
  // ------------------------------------------------------------------
  const stopStreaming = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;

    // Flush any remaining tokens and mark the message as done.
    if (streamingMsgIdRef.current !== null) {
      const msgId = streamingMsgIdRef.current;
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      const remaining = pendingTokensRef.current;
      pendingTokensRef.current = "";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId
            ? { ...m, text: m.text + remaining, isStreaming: false }
            : m
        )
      );
      streamingMsgIdRef.current = null;
    }

    setStreaming(false);
    setInflight(false);
  }, []);

  // ------------------------------------------------------------------
  // Send handler — tries streaming first, falls back to sync
  // ------------------------------------------------------------------
  const handleSend = async () => {
    const text = input.trim();
    if (!text || inflight) return;

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
      return;
    }

    const base = Date.now();
    setMessages((prev) => [
      ...prev,
      { id: base, sender: "user", text, document_id: attachment.documentId },
    ]);
    setInflight(true);

    try {
      // --- Attempt streaming first ---
      const controller = new AbortController();
      abortControllerRef.current = controller;

      const aiMsgId = base + 1;
      const chatOptions = {
        matchCount: retrievalSettings.matchCount,
        scope: retrievalSettings.scope,
        sessionId,
      };

      // Add empty AI message with isStreaming flag.
      setMessages((prev) => [
        ...prev,
        { id: aiMsgId, sender: "ai", text: "", isStreaming: true },
      ]);
      setStreaming(true);

      try {
        const generator = sendMessageStream(
          text,
          attachment.documentId,
          chatOptions,
          controller.signal,
        );
        await consumeStream(generator, aiMsgId);
      } catch (e) {
        if (e instanceof StreamingDisabledError) {
          // --- Fallback to sync path ---
          setStreaming(false);

          // Remove the empty streaming message, we'll add a proper one.
          setMessages((prev) => prev.filter((m) => m.id !== aiMsgId));

          const response = await sendMessage(text, attachment.documentId, chatOptions);
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
        } else if (e instanceof DOMException && e.name === "AbortError") {
          // Stream was cancelled by the user — already handled by stopStreaming.
        } else {
          throw e;
        }
      }

      abortControllerRef.current = null;
    } catch (e) {
      let errorText = "Something went wrong. Please try again.";
      if (e instanceof ChatError) {
        errorText = e.message;
        if (e.code === "no_document") {
          setAttachment((curr) => (curr ? { ...curr, status: "failed" } : curr));
        }
      }
      // If we already have an AI message from streaming, update it with error.
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
      setInflight(false);
      setStreaming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    void handleSend();
  };

  const handleBeforeUpload = async () => {
    if (!attachment) return;
    const out = await deleteDocument(attachment.documentId);
    if (out.status === "gone") {
      removeUploadedDocument(attachment.documentId);
      setAttachment(null);
      setRemoveError(null);
      return;
    }
    if (out.status === "conflict") {
      throw new Error(out.message);
    }
    throw new Error(out.message);
  };

  const handleUploadAccepted = (payload: {
    fileName: string;
    documentId: string;
    statusEndpoint: string;
    queuePosition?: number;
  }) => {
    setRemoveError(null);
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
    input,
    setInput,
    inflight,
    streaming,
    attachment,
    removeError,
    sendDisabled,
    bottomRef,
    poll,
    handleSend,
    handleKeyDown,
    handleBeforeUpload,
    handleUploadAccepted,
    handleRemoveAttachment,
    stopStreaming,
  };
}

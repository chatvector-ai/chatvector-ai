"use client";

import { useState, useRef, useEffect } from "react";
import {
  deleteDocument,
  sendMessage,
  ChatError,
  type AttachmentState,
  type Message,
} from "../api";
import { useDocumentPolling } from "./useDocumentPolling";

const welcomeMessages: Message[] = [
  {
    id: 1,
    sender: "ai",
    text: "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it.",
  },
];

export function useChat() {
  const [messages, setMessages] = useState<Message[]>(welcomeMessages);
  const [input, setInput] = useState("");
  const [attachment, setAttachment] = useState<AttachmentState | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [inflight, setInflight] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const readyAnnouncedForDocRef = useRef<string | null>(null);

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
  }, [poll.status, poll.chunks, attachment]);

  useEffect(() => {
    if (poll.status !== "failed" || !attachment || attachment.status !== "processing") {
      return;
    }
    const docId = attachment.documentId;
    setAttachment((curr) =>
      curr?.documentId === docId ? { ...curr, status: "failed" } : curr
    );
  }, [poll.status, attachment]);

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
      const response = await sendMessage(text, attachment.documentId);
      setMessages((prev) => [
        ...prev,
        {
          id: base + 1,
          sender: "ai",
          text: response.answer,
          sources: response.sources,
          chunks: response.chunks,
        },
      ]);
    } catch (e) {
      let errorText = "Something went wrong. Please try again.";
      if (e instanceof ChatError) {
        errorText = e.message;
        if (e.code === "no_document") {
          setAttachment((curr) => (curr ? { ...curr, status: "failed" } : curr));
        }
      }
      setMessages((prev) => [...prev, { id: base + 1, sender: "ai", text: errorText }]);
    } finally {
      setInflight(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") void handleSend();
  };

  const handleBeforeUpload = async () => {
    if (!attachment) return;
    const out = await deleteDocument(attachment.documentId);
    if (out === "gone") {
      setAttachment(null);
      setRemoveError(null);
      return;
    }
    if (out === "conflict") {
      throw new Error(
        "Wait for the current document to finish processing, or remove it, before uploading another."
      );
    }
    throw new Error("Could not remove the previous document. Try again.");
  };

  const handleUploadAccepted = (payload: {
    fileName: string;
    documentId: string;
    statusEndpoint: string;
  }) => {
    setRemoveError(null);
    setAttachment({
      fileName: payload.fileName,
      documentId: payload.documentId,
      statusEndpoint: payload.statusEndpoint,
      status: "processing",
    });
  };

  const handleRemoveAttachment = async () => {
    if (!attachment) return;
    setRemoveError(null);
    try {
      const out = await deleteDocument(attachment.documentId);
      if (out === "gone") {
        setAttachment(null);
        return;
      }
      if (out === "conflict") {
        setRemoveError("Can't remove while the document is queued or processing.");
        return;
      }
      setRemoveError("Could not remove the document. Try again.");
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
  };
}

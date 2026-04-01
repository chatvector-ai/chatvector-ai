"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, FileText, X } from "lucide-react";
import UploadButton from "../components/UploadButton";
import UploadModal from "../components/UploadModal";
import {
  deleteDocument,
  DocumentNotFoundError,
  getDocumentStatus,
  sendMessage,
  ChatError,
} from "../lib/api";
import type { ChatSource } from "../lib/api";

type Message = {
  id: number;
  sender: "ai" | "user";
  text: string;
  document_id?: string;
  sources?: ChatSource[];
};

type AttachmentState = {
  fileName: string;
  documentId: string;
  statusEndpoint: string;
  status: "processing" | "ready" | "failed";
};

const welcomeMessages: Message[] = [
  { id: 1, sender: "ai", text: "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it." },
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(welcomeMessages);
  const [input, setInput] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [attachment, setAttachment] = useState<AttachmentState | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [inflight, setInflight] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, inflight]);

  useEffect(() => {
    if (!attachment || attachment.status !== "processing") return;

    const docId = attachment.documentId;
    const statusPath = attachment.statusEndpoint;
    let cancelled = false;

    const poll = async () => {
      if (cancelled) return;
      try {
        const { status: st } = await getDocumentStatus(statusPath);
        if (st === "completed") {
          let readyName = "";
          setAttachment((curr) => {
            if (!curr || curr.documentId !== docId || curr.status !== "processing") {
              return curr;
            }
            readyName = curr.fileName;
            return { ...curr, status: "ready" };
          });
          if (readyName) {
            setMessages((prev) => [
              ...prev,
              {
                id: Date.now(),
                sender: "ai",
                text: `Document "${readyName}" is ready. You can ask questions about it.`,
              },
            ]);
          }
        } else if (st === "failed") {
          setAttachment((curr) =>
            curr?.documentId === docId ? { ...curr, status: "failed" } : curr
          );
        }
      } catch (e) {
        if (e instanceof DocumentNotFoundError) {
          setAttachment((curr) =>
            curr?.documentId === docId ? { ...curr, status: "failed" } : curr
          );
          return;
        }
        /* next interval */
      }
    };

    void poll();
    const interval = setInterval(poll, 2500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps are the primitive values we react to, not the object ref
  }, [attachment?.documentId, attachment?.status]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || inflight) return;
    setInput("");

    if (attachment?.status !== "ready") {
      setMessages((prev) => [
        ...prev,
        { id: Date.now(), sender: "user", text },
        {
          id: Date.now() + 1,
          sender: "ai",
          text: "Please upload a document first so I can answer questions about it.",
        },
      ]);
      return;
    }

    setMessages((prev) => [
      ...prev,
      { id: Date.now(), sender: "user", text, document_id: attachment.documentId },
    ]);
    setInflight(true);

    try {
      const response = await sendMessage(text, attachment.documentId);
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now(),
          sender: "ai",
          text: response.answer,
          sources: response.sources,
        },
      ]);
    } catch (e) {
      let errorText = "Something went wrong. Please try again.";
      if (e instanceof ChatError) {
        errorText = e.message;
        if (e.code === "no_document") {
          setAttachment((curr) =>
            curr ? { ...curr, status: "failed" } : curr
          );
        }
      }
      setMessages((prev) => [
        ...prev,
        { id: Date.now(), sender: "ai", text: errorText },
      ]);
    } finally {
      setInflight(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSend();
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

  const chipLabel =
    attachment?.status === "processing"
      ? "Processing…"
      : attachment?.status === "failed"
        ? "Processing failed"
        : attachment?.fileName ?? "";

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-white">
      {showModal && (
        <UploadModal
          onClose={() => setShowModal(false)}
          onBeforeUpload={handleBeforeUpload}
          onUploadAccepted={handleUploadAccepted}
        />
      )}

      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex items-end gap-2 ${msg.sender === "user" ? "flex-row-reverse" : "flex-row"}`}
          >
            <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center ${msg.sender === "ai" ? "bg-indigo-600" : "bg-gray-600"}`}>
              {msg.sender === "ai" ? <Bot size={16} /> : <User size={16} />}
            </div>
            <div className={`max-w-[75%] md:max-w-[60%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${msg.sender === "ai" ? "bg-gray-800 text-gray-100 rounded-bl-none" : "bg-indigo-600 text-white rounded-br-none"}`}>
              {msg.text}
            </div>
          </div>
        ))}
        {inflight && (
          <div className="flex items-end gap-2">
            <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-indigo-600">
              <Bot size={16} />
            </div>
            <div className="px-4 py-3 rounded-2xl rounded-bl-none bg-gray-800 text-gray-400 text-sm animate-pulse">
              Thinking...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {attachment && (
        <div className="px-4 py-2 bg-gray-900 border-t border-gray-800 flex items-center gap-2">
          <FileText
            size={14}
            className={
              attachment.status === "failed"
                ? "text-red-400"
                : attachment.status === "processing"
                  ? "text-amber-400"
                  : "text-indigo-400"
            }
          />
          <span className="text-xs text-gray-400">Active document:</span>
          <span
            className={`text-xs font-medium flex-1 truncate ${
              attachment.status === "failed"
                ? "text-red-400"
                : attachment.status === "processing"
                  ? "text-amber-400"
                  : "text-indigo-400"
            }`}
          >
            {chipLabel}
          </span>
          <button
            type="button"
            onClick={handleRemoveAttachment}
            className="p-1 rounded-md text-gray-500 hover:text-white hover:bg-gray-800 transition shrink-0"
            aria-label="Remove attachment"
          >
            <X size={16} />
          </button>
        </div>
      )}
      {removeError && (
        <p className="px-4 pb-1 text-xs text-red-400 bg-gray-900">{removeError}</p>
      )}

      <div className="px-4 py-3 border-t border-gray-800 bg-gray-900">
        <div className="flex items-center gap-2 bg-gray-800 rounded-xl px-4 py-2">
          <UploadButton onClick={() => setShowModal(true)} />
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your document..."
            disabled={inflight}
            className="flex-1 bg-transparent outline-none text-sm text-white placeholder-gray-500 disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={inflight || !input.trim()}
            className="w-8 h-8 rounded-lg bg-indigo-600 hover:bg-indigo-500 flex items-center justify-center transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send size={15} />
          </button>
        </div>
        <p className="text-center text-xs text-gray-600 mt-2">
          ChatVector may make mistakes. Always verify important information.
        </p>
      </div>
    </div>
  );
}

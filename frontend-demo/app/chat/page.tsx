"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User } from "lucide-react";
import UploadButton from "../components/UploadButton";
import UploadModal from "../components/UploadModal";
import AttachmentChip from "../components/AttachmentChip";
import {
  deleteDocument,
  sendMessage,
  ChatError,
  type AttachmentState,
  type ChatSource,
} from "../lib/api";
import { useDocumentPolling } from "../lib/hooks/useDocumentPolling";

type Message = {
  id: number;
  sender: "ai" | "user";
  text: string;
  document_id?: string;
  sources?: ChatSource[];
};

const welcomeMessages: Message[] = [
  {
    id: 1,
    sender: "ai",
    text: "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it.",
  },
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(welcomeMessages);
  const [input, setInput] = useState("");
  const [showModal, setShowModal] = useState(false);
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
    if (poll.status === "ready") {
      setShowModal(false);
    }
  }, [poll.status]);

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
    if (attachment?.status === "processing") return;

    setInput("");

    if (attachment?.status !== "ready") {
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
        <AttachmentChip
          fileName={attachment.fileName}
          status={attachment.status}
          stage={poll.stage}
          chunks={poll.chunks}
          awaitingProcessing={poll.awaitingProcessing}
          onRemove={() => void handleRemoveAttachment()}
        />
      )}
      {attachment?.status === "processing" && (
        <p className="px-4 pb-1 text-xs text-amber-400 bg-gray-900">
          Document still processing — sending is disabled until it is ready.
        </p>
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
            placeholder={
              attachment?.status === "processing"
                ? "Waiting for document to be ready..."
                : "Ask about your document..."
            }
            disabled={inflight}
            className="flex-1 bg-transparent outline-none text-sm text-white placeholder-gray-500 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void handleSend()}
            disabled={sendDisabled}
            title={
              inflight
                ? "Waiting for response..."
                : attachment?.status === "processing"
                  ? "Document still processing..."
                  : !input.trim()
                    ? "Type a message to send"
                    : undefined
            }
            className={`w-8 h-8 rounded-lg flex items-center justify-center transition ${
              sendDisabled
                ? "bg-gray-600 cursor-not-allowed opacity-50"
                : "bg-indigo-600 hover:bg-indigo-500 cursor-pointer"
            }`}
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

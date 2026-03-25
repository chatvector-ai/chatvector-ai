"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, FileText } from "lucide-react";
import UploadButton from "../components/UploadButton";
import UploadModal from "../components/UploadModal";

type Message = {
  id: number;
  sender: "ai" | "user";
  text: string;
};

const sampleMessages: Message[] = [
  { id: 1, sender: "ai", text: "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it." },
  { id: 2, sender: "user", text: "What is RAG?" },
  { id: 3, sender: "ai", text: "RAG stands for Retrieval-Augmented Generation. It retrieves relevant context from your documents before generating an answer." },
  { id: 4, sender: "user", text: "That sounds cool! Can I upload a PDF?" },
];

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>(sampleMessages);
  const [input, setInput] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), sender: "user", text: input.trim() },
    ]);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSend();
  };

  const handleUploadSuccess = (fileName: string) => {
    setUploadedFile(fileName);
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), sender: "ai", text: `Document "${fileName}" uploaded! You can now ask questions about it.` },
    ]);
  };

  return (
    <div className="flex flex-col h-screen bg-gray-950 text-white">
      {showModal && (
        <UploadModal
          onClose={() => setShowModal(false)}
          onUploadSuccess={handleUploadSuccess}
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
        <div ref={bottomRef} />
      </div>

      {uploadedFile && (
        <div className="px-4 py-2 bg-gray-900 border-t border-gray-800 flex items-center gap-2">
          <FileText size={14} className="text-indigo-400" />
          <span className="text-xs text-gray-400">Active document:</span>
          <span className="text-xs text-indigo-400 font-medium">{uploadedFile}</span>
        </div>
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
            className="flex-1 bg-transparent outline-none text-sm text-white placeholder-gray-500"
          />
          <button
            onClick={handleSend}
            className="w-8 h-8 rounded-lg bg-indigo-600 hover:bg-indigo-500 flex items-center justify-center transition"
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
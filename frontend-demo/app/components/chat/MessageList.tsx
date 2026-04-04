"use client";

import type { RefObject } from "react";
import { Bot, User } from "lucide-react";
import type { ChatSource } from "../../lib/api";
import type { Message } from "../../lib/hooks/useChat";

type Props = {
  messages: Message[];
  inflight: boolean;
  bottomRef: RefObject<HTMLDivElement | null>;
};

function deduplicatedSources(sources: ChatSource[]): ChatSource[] {
  const seen = new Set<string>();
  return sources.filter((s) => {
    const key = `${s.file_name}::${s.page_number ?? "null"}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export default function MessageList({ messages, inflight, bottomRef }: Props) {
  return (
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
            {msg.sender === "ai" && msg.sources && msg.sources.length > 0 && (
              <div className="mt-2 flex flex-col gap-1">
                {deduplicatedSources(msg.sources).map((s, i) => (
                  <span key={i} className="text-xs text-gray-500">
                    {s.file_name}
                    {s.page_number != null ? ` · p.${s.page_number}` : ""}
                  </span>
                ))}
              </div>
            )}
            {msg.sender === "ai" && msg.chunks === 0 && (
              <p className="mt-1 text-xs text-gray-500 italic">
                No relevant content found in this document.
              </p>
            )}
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
  );
}

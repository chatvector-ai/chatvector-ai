"use client";

import type { RefObject } from "react";
import { useState, useEffect, useRef } from "react";
import { Bot, User } from "lucide-react";
import type { ChatSource, Message } from "../../lib/api";

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

// Welcome message (id: 1) and error messages (no sources/chunks) skip animation.
function shouldAnimate(msg: Message): boolean {
  if (msg.sender !== "ai") return false;
  if (msg.id === 1) return false;
  if (msg.sources === undefined && msg.chunks === undefined) return false;
  return true;
}

// Cap total animation time at 6 seconds for long responses.
const MAX_ANIM_MS = 6000;
const BASE_INTERVAL_MS = 18;

function charInterval(textLength: number): number {
  const totalAtBase = textLength * BASE_INTERVAL_MS;
  return totalAtBase > MAX_ANIM_MS
    ? Math.max(1, Math.floor(MAX_ANIM_MS / textLength))
    : BASE_INTERVAL_MS;
}

export default function MessageList({ messages, inflight, bottomRef }: Props) {
  const [animatingId, setAnimatingId] = useState<number | null>(null);
  const [displayedText, setDisplayedText] = useState("");
  const [animDone, setAnimDone] = useState(true);

  // Refs let us avoid stale closures inside setInterval callbacks.
  const animatingIdRef = useRef<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const charIndexRef = useRef(0);

  useEffect(() => {
    const lastAnimatable = [...messages].reverse().find(shouldAnimate);
    if (!lastAnimatable) return;
    // Already handling this message — don't restart.
    if (lastAnimatable.id === animatingIdRef.current) return;

    // Cancel any in-progress animation.
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    const text = lastAnimatable.text;
    const interval = charInterval(text.length);

    animatingIdRef.current = lastAnimatable.id;
    setAnimatingId(lastAnimatable.id);
    setDisplayedText("");
    setAnimDone(false);
    charIndexRef.current = 0;

    intervalRef.current = setInterval(() => {
      charIndexRef.current += 1;
      setDisplayedText(text.slice(0, charIndexRef.current));
      if (charIndexRef.current >= text.length) {
        clearInterval(intervalRef.current!);
        intervalRef.current = null;
        setAnimDone(true);
      }
    }, interval);
  }, [messages]);

  // Clean up interval on unmount.
  useEffect(() => {
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 space-y-4">
      {messages.map((msg) => {
        const isAnimating = msg.id === animatingId;
        const text = isAnimating ? displayedText : msg.text;
        const sourcesVisible = isAnimating ? animDone : true;

        return (
          <div
            key={msg.id}
            className={`flex items-end gap-2 ${msg.sender === "user" ? "flex-row-reverse" : "flex-row"}`}
          >
            <div
              className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center ${
                msg.sender === "ai" ? "bg-accent text-black" : "bg-surface border border-border"
              }`}
            >
              {msg.sender === "ai" ? <Bot size={16} /> : <User size={16} />}
            </div>
            <div
              className={`max-w-[75%] md:max-w-[60%] whitespace-pre-wrap break-words px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                msg.sender === "ai" ? "bg-surface text-foreground rounded-bl-none" : "bg-accent text-black rounded-br-none"
              }`}
            >
              {text}
              {msg.sender === "ai" && msg.sources && msg.sources.length > 0 && sourcesVisible && (
                <div className="mt-2 flex flex-col gap-1">
                  {deduplicatedSources(msg.sources).map((s, i) => (
                    <span key={i} className="text-xs text-muted">
                      {s.file_name}
                      {s.page_number != null ? ` · p.${s.page_number}` : ""}
                    </span>
                  ))}
                </div>
              )}
              {msg.sender === "ai" && msg.chunks === 0 && sourcesVisible && (
                <p className="mt-1 text-xs text-muted italic">
                  No relevant content found in this document.
                </p>
              )}
            </div>
          </div>
        );
      })}
      {inflight && (
        <div className="flex items-end gap-2">
          <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-accent text-black">
            <Bot size={16} />
          </div>
          <div className="px-4 py-3 rounded-2xl rounded-bl-none bg-surface text-muted text-sm animate-pulse">
            Thinking...
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}

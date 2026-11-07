"use client";

import type { RefObject } from "react";
import { useState, useEffect, useRef } from "react";
import { Bot, User } from "lucide-react";
import { type Message } from "../../lib/api";
import AiResponseContent from "./AiResponseContent";

type Props = {
  messages: Message[];
  inflight: boolean;
  streaming: boolean;
  historyLoading?: boolean;
  bottomRef: RefObject<HTMLDivElement | null>;
};

// Welcome message (id: 1) and transport errors (no sources/chunks) skip animation.
// Streamed messages also skip the fake animation — they render tokens in real time.
function shouldAnimate(msg: Message): boolean {
  if (msg.sender !== "ai") return false;
  if (msg.id === 1) return false;
  if (msg.isStreaming !== undefined) return false; // real streaming — no fake animation
  if (msg.sources === undefined && msg.chunks === undefined && !msg.error) return false;
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

export default function MessageList({
  messages,
  inflight,
  streaming,
  historyLoading = false,
  bottomRef,
}: Props) {
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

  // Auto-scroll to bottom when streaming tokens arrive.
  useEffect(() => {
    if (streaming) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streaming, bottomRef]);

  return (
    <div
      className="min-h-0 flex-1 overflow-y-auto px-4 py-6 space-y-4"
      aria-busy={historyLoading || inflight || streaming}
      aria-live="polite"
    >
      {historyLoading && messages.length === 0 && (
        <div className="flex items-end gap-2">
          <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-surface border border-border text-muted">
            <Bot size={16} />
          </div>
          <div className="px-4 py-3 rounded-2xl rounded-bl-none bg-surface text-muted text-base animate-pulse">
            Loading conversation...
          </div>
        </div>
      )}
      {messages.map((msg) => {
        const isRealStreaming = msg.isStreaming === true;
        const wasStreamed = msg.isStreaming !== undefined;
        const isAnimating = !wasStreamed && msg.id === animatingId;
        const text = isAnimating ? displayedText : msg.text;
        const detailsVisible = isRealStreaming
          ? false // hide details while streaming tokens
          : isAnimating
            ? animDone
            : true;

        return (
          <div
            key={msg.id}
            className={`flex items-end gap-2 ${msg.sender === "user" ? "flex-row-reverse" : "flex-row"}`}
          >
            <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-surface border border-border text-muted">
              {msg.sender === "ai" ? <Bot size={16} /> : <User size={16} />}
            </div>
            <div
              className={`max-w-[75%] md:max-w-[60%] break-words px-4 py-3 rounded-2xl text-base leading-relaxed ${
                msg.sender === "ai"
                  ? "bg-surface text-foreground rounded-bl-none"
                  : "chat-bubble-user rounded-br-none whitespace-pre-wrap"
              }`}
            >
              {msg.sender === "user" ? (
                text
              ) : (
                <AiResponseContent
                  text={text}
                  error={msg.error}
                  sources={msg.sources}
                  chunks={msg.chunks}
                  model={msg.model}
                  latencyMs={msg.latency_ms}
                  question={msg.question}
                  retrievalDebug={msg.retrieval_debug}
                  detailsVisible={detailsVisible}
                  isStreaming={isRealStreaming}
                />
              )}
            </div>
          </div>
        );
      })}
      {inflight && !streaming && (
        <div className="flex items-end gap-2">
          <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-surface border border-border text-muted">
            <Bot size={16} />
          </div>
          <div className="px-4 py-3 rounded-2xl rounded-bl-none bg-surface text-muted text-base animate-pulse">
            Thinking...
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  );
}

"use client";

import type { RefObject } from "react";
import { useState, useEffect, useRef } from "react";
import { Bot, User } from "lucide-react";
import { softFailureMessage, type Message } from "../../lib/api";
import {
  deduplicatedSources,
  formatCitationLine,
  formatResponseMetadata,
} from "../../lib/citations";
import RetrievalInspector from "../RetrievalInspector";

type Props = {
  messages: Message[];
  inflight: boolean;
  streaming: boolean;
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

export default function MessageList({ messages, inflight, streaming, bottomRef }: Props) {
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
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 space-y-4">
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
        const metadata = formatResponseMetadata({
          chunks: msg.chunks,
          model: msg.model,
          latency_ms: msg.latency_ms,
        });

        return (
          <div
            key={msg.id}
            className={`flex items-end gap-2 ${msg.sender === "user" ? "flex-row-reverse" : "flex-row"}`}
          >
            <div
              className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center ${
                msg.sender === "ai"
                  ? "bg-accent text-background"
                  : "bg-surface border border-border"
              }`}
            >
              {msg.sender === "ai" ? <Bot size={16} /> : <User size={16} />}
            </div>
            <div
              className={`max-w-[75%] md:max-w-[60%] whitespace-pre-wrap break-words px-4 py-3 rounded-2xl text-base leading-relaxed ${
                msg.sender === "ai"
                  ? "bg-surface text-foreground rounded-bl-none"
                  : "bg-accent text-background rounded-br-none"
              }`}
            >
              {msg.sender === "ai" && msg.error && detailsVisible && (
                <p className="mb-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-500">
                  {softFailureMessage(msg.error)}
                </p>
              )}
              {/* Streaming: show text with blinking cursor */}
              {isRealStreaming ? (
                text ? (
                  <span>
                    {text}
                    <span className="inline-block w-[2px] h-[1em] bg-accent animate-pulse ml-0.5 align-text-bottom" />
                  </span>
                ) : (
                  <span className="text-muted animate-pulse">Streaming...</span>
                )
              ) : (
                text
              )}
              {msg.sender === "ai" && msg.sources && msg.sources.length > 0 && detailsVisible && (
                <div className="mt-2 flex flex-col gap-1">
                  {deduplicatedSources(msg.sources).map((source, index) => (
                    <span key={index} className="text-sm text-muted">
                      {formatCitationLine(source)}
                    </span>
                  ))}
                </div>
              )}
              {msg.sender === "ai" && msg.chunks === 0 && detailsVisible && (
                <p className="mt-1 text-sm text-muted italic">
                  No relevant content found in this document.
                </p>
              )}
              {msg.sender === "ai" && metadata && detailsVisible && (
                <p className="mt-2 text-xs text-muted">{metadata}</p>
              )}
              {msg.sender === "ai" && detailsVisible && (
                <RetrievalInspector
                  data={{
                    question: msg.question,
                    retrieval_debug: msg.retrieval_debug,
                    sources: msg.sources,
                    chunks: msg.chunks,
                    model: msg.model,
                    latency_ms: msg.latency_ms,
                  }}
                />
              )}
            </div>
          </div>
        );
      })}
      {inflight && !streaming && (
        <div className="flex items-end gap-2">
          <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center bg-accent text-background">
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

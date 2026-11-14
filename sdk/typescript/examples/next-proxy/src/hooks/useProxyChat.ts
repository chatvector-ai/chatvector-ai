"use client";

import { useCallback, useRef, useState } from "react";
import type { ChatSource } from "@chatvector/sdk";
import {
  ProxyClient,
  StreamingDisabledError,
  type ProxyChatRequest,
} from "../proxy-client.js";

export type UseProxyChatOptions = {
  client: ProxyClient;
  sessionId?: string | null;
  onSessionId?: (sessionId: string) => void;
};

export type UseProxyChatResult = {
  answer: string;
  sources: ChatSource[];
  isStreaming: boolean;
  error: string | null;
  send: (request: Omit<ProxyChatRequest, "sessionId">) => Promise<void>;
  stop: () => void;
  reset: () => void;
};

/**
 * Proxy-backed chat hook with streaming first and a non-stream fallback when
 * the upstream API disables SSE.
 */
export function useProxyChat(options: UseProxyChatOptions): UseProxyChatResult {
  const { client, sessionId, onSessionId } = options;
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<ChatSource[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  }, []);

  const reset = useCallback(() => {
    stop();
    setAnswer("");
    setSources([]);
    setError(null);
  }, [stop]);

  const send = useCallback(
    async (request: Omit<ProxyChatRequest, "sessionId">) => {
      stop();
      const controller = new AbortController();
      abortRef.current = controller;
      setAnswer("");
      setSources([]);
      setError(null);
      setIsStreaming(true);

      const payload: ProxyChatRequest = {
        ...request,
        sessionId: sessionId ?? undefined,
      };

      try {
        try {
          for await (const event of client.streamChat(payload, {
            signal: controller.signal,
          })) {
            if (event.type === "token") {
              setAnswer((prev) => prev + event.content);
            } else if (event.type === "complete") {
              setSources(event.sources);
              if (event.sessionId && onSessionId) {
                onSessionId(event.sessionId);
              }
            }
          }
        } catch (cause) {
          if (cause instanceof StreamingDisabledError) {
            const result = await client.chat(payload, {
              signal: controller.signal,
            });
            if (result.sessionId && onSessionId) {
              onSessionId(result.sessionId);
            }
            if (result.response.status === "error") {
              const errorMessage =
                result.response.error?.message ??
                result.response.error?.code ??
                "Chat request failed";
              setError(errorMessage);
              return;
            }
            setAnswer(result.response.answer);
            setSources(result.response.sources);
          } else {
            throw cause;
          }
        }
      } catch (cause) {
        if (cause instanceof DOMException && cause.name === "AbortError") {
          return;
        }
        setError(cause instanceof Error ? cause.message : "Chat request failed");
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
        setIsStreaming(false);
      }
    },
    [client, onSessionId, sessionId, stop],
  );

  return {
    answer,
    sources,
    isStreaming,
    error,
    send,
    stop,
    reset,
  };
}

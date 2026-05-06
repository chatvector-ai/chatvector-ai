"use client";

import { useEffect, useRef, useState } from "react";
import {
  DocumentNotFoundError,
  getDocumentStatus,
} from "../api";
import { API_BASE } from "../api";

export type PolledDocumentStatus = "processing" | "ready" | "failed";

function mapApiStatusToUi(apiStatus: string): PolledDocumentStatus {
  if (apiStatus === "completed") return "ready";
  if (apiStatus === "failed") return "failed";
  return "processing";
}

export function useDocumentPolling(
  documentId: string | undefined,
  statusEndpoint: string | undefined,
  status: PolledDocumentStatus | undefined
): {
  status: PolledDocumentStatus | undefined;
  stage: string | undefined;
  chunks: { total: number; processed: number } | undefined;
  awaitingProcessing: boolean;
} {
  const [polledUiStatus, setPolledUiStatus] = useState<
    PolledDocumentStatus | undefined
  >(undefined);
  const [stage, setStage] = useState<string | undefined>(undefined);
  const [chunks, setChunks] = useState<
    { total: number; processed: number } | undefined
  >(undefined);
  const [awaitingProcessing, setAwaitingProcessing] = useState(false);

  // A toggle for environments/situations where SSE fails
  const [useFallbackPolling, setUseFallbackPolling] = useState(false);

  const enabled =
    Boolean(documentId && statusEndpoint) && status === "processing";

  const docKey = documentId ?? "";
  const prevDocKeyRef = useRef<string>("");

  useEffect(() => {
    if (docKey !== prevDocKeyRef.current) {
      prevDocKeyRef.current = docKey;
      setPolledUiStatus(undefined);
      setStage(undefined);
      setChunks(undefined);
      setAwaitingProcessing(false);
      setUseFallbackPolling(false);
    }
  }, [docKey]);

  useEffect(() => {
    if (!enabled || !documentId || !statusEndpoint) {
      return;
    }

    setAwaitingProcessing(true);

    let cancelled = false;
    const path = statusEndpoint;
    let eventSource: EventSource | null = null;
    let interval: ReturnType<typeof setInterval> | null = null;

    if (!useFallbackPolling && typeof window !== "undefined" && window.EventSource) {
      // 1. Try SSE first
      const sseUrl = `${API_BASE}${path}/stream`;
      eventSource = new EventSource(sseUrl);

      eventSource.addEventListener("status", (event) => {
        if (cancelled) return;
        setAwaitingProcessing(false);

        try {
          const payload = JSON.parse(event.data);

          const rawStage =
            typeof payload.stage === "string" && payload.stage.length > 0
              ? payload.stage
              : payload.status;
          setStage(rawStage);

          const c = payload.chunks;
          if (
            c &&
            typeof c.total === "number" &&
            typeof c.processed === "number"
          ) {
            setChunks({ total: c.total, processed: c.processed });
          } else {
            setChunks(undefined);
          }

          const ui = mapApiStatusToUi(payload.status);
          setPolledUiStatus(ui);

          if (payload.status === "completed" || payload.status === "failed") {
            eventSource?.close();
          }
        } catch (e) {
          console.error("Failed to parse SSE payload", e);
        }
      });

      eventSource.addEventListener("error", (event) => {
        if (cancelled) return;

        try {
          if (event && "data" in event && typeof (event as MessageEvent).data === "string") {
             const payload = JSON.parse((event as MessageEvent).data);
             if (payload.message === "Document not found.") {
                 setAwaitingProcessing(false);
                 setPolledUiStatus("failed");
                 eventSource?.close();
                 return;
             }
          }
        } catch {
          // ignore parsing error
        }

        console.warn("SSE connection error or closed, falling back to polling");
        eventSource?.close();
        setUseFallbackPolling(true);
      });
    } else {
      // 2. Fallback Polling (setInterval)
      const poll = async () => {
        if (cancelled) return;
        try {
          const payload = await getDocumentStatus(path);
          if (cancelled) return;

          setAwaitingProcessing(false);

          const rawStage =
            typeof payload.stage === "string" && payload.stage.length > 0
              ? payload.stage
              : payload.status;
          setStage(rawStage);

          const c = payload.chunks;
          if (
            c &&
            typeof c.total === "number" &&
            typeof c.processed === "number"
          ) {
            setChunks({ total: c.total, processed: c.processed });
          } else {
            setChunks(undefined);
          }

          const ui = mapApiStatusToUi(payload.status);
          setPolledUiStatus(ui);
          
          if (payload.status === "completed" || payload.status === "failed") {
              if (interval) clearInterval(interval);
          }
        } catch (e) {
          if (e instanceof DocumentNotFoundError) {
            if (cancelled) return;
            setAwaitingProcessing(false);
            setPolledUiStatus("failed");
            if (interval) clearInterval(interval);
            return;
          }
          /* next interval */
        }
      };

      void poll();
      interval = setInterval(poll, 2500);
    }

    return () => {
      cancelled = true;
      if (eventSource) {
        eventSource.close();
      }
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [enabled, documentId, statusEndpoint, useFallbackPolling]);

  return {
    status: polledUiStatus,
    stage,
    chunks,
    awaitingProcessing: enabled && awaitingProcessing,
  };
}

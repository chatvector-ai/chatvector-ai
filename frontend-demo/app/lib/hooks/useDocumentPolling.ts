"use client";

import { useEffect, useRef, useState } from "react";
import {
  DocumentNotFoundError,
  getDocumentStatus,
  API_BASE,
} from "../api";
import { PIPELINE_STAGES } from "../stageLabels";

export type PolledDocumentStatus = "processing" | "ready" | "failed";

function mapApiStatusToUi(apiStatus: string): PolledDocumentStatus {
  if (apiStatus === "completed") return "ready";
  if (apiStatus === "failed") return "failed";
  return "processing";
}

/** Format a duration in milliseconds to a human-readable string. */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}
function stagesBefore(currentStage: string): string[] {
  const idx = PIPELINE_STAGES.indexOf(currentStage as never);
  if (idx <= 0) return [];
  return Array.from(PIPELINE_STAGES.slice(0, idx));
}

/**
 * Resolve the display stage from a raw SSE/poll payload.
 *
 * - On failure: use error.stage (the pipeline step that failed) so the
 *   pipeline list can highlight the correct row. Fall back to the last
 *   known non-failure stage string.
 * - "uploaded" is only emitted by the synchronous path and maps to "queued"
 *   (the nearest PIPELINE_STAGES entry) to avoid an indexOf miss.
 * - "failed" itself is not a pipeline step — handled via the `failed` flag.
 */
function resolveDisplayStage(payload: {
  status: string;
  stage?: string;
  error?: { stage?: string } | null;
}): string {
  if (payload.status === "failed") {
    const errorStage = payload.error?.stage;
    if (errorStage && errorStage !== "failed" && PIPELINE_STAGES.indexOf(errorStage as never) >= 0) {
      return errorStage;
    }
    // fall back to the last stage field the server sent, or a safe default
    return payload.stage ?? "extracting";
  }
  if (payload.status === "uploaded" || payload.stage === "uploaded") {
    return "queued";
  }
  if (typeof payload.stage === "string" && payload.stage.length > 0) {
    return payload.stage;
  }
  return payload.status;
}

export function useDocumentPolling(
  documentId: string | undefined,
  statusEndpoint: string | undefined,
  status: PolledDocumentStatus | undefined
): {
  status: PolledDocumentStatus | undefined;
  stage: string | undefined;
  completedStages: string[];
  chunks: { total: number; processed: number } | undefined;
  awaitingProcessing: boolean;
  processingTime: string | undefined;
  errorMessage: string | undefined;
} {
  const [polledUiStatus, setPolledUiStatus] = useState<
    PolledDocumentStatus | undefined
  >(undefined);
  const [stage, setStage] = useState<string | undefined>(undefined);
  const [completedStages, setCompletedStages] = useState<string[]>([]);
  const [chunks, setChunks] = useState<
    { total: number; processed: number } | undefined
  >(undefined);
  const [awaitingProcessing, setAwaitingProcessing] = useState(false);
  const [processingTime, setProcessingTime] = useState<string | undefined>(undefined);
  const [errorMessage, setErrorMessage] = useState<string | undefined>(undefined);

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
      setCompletedStages([]);
      setChunks(undefined);
      setAwaitingProcessing(false);
      setUseFallbackPolling(false);
      setProcessingTime(undefined);
      setErrorMessage(undefined);
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

          const rawStage = resolveDisplayStage(payload);
          setStage(rawStage);
          setCompletedStages(stagesBefore(rawStage));
          if (payload.status === "failed") {
           setErrorMessage(payload.error?.message);
          }

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

          // Compute processing duration when ingestion completes
          if (ui === "ready" && payload.created_at && payload.updated_at) {
            const created = new Date(payload.created_at).getTime();
            const updated = new Date(payload.updated_at).getTime();
            if (!isNaN(created) && !isNaN(updated) && updated > created) {
              setProcessingTime(formatDuration(updated - created));
            }
          }

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

          const rawStage = resolveDisplayStage(payload);
          setStage(rawStage);
          setCompletedStages(stagesBefore(rawStage));
          if (payload.status === "failed") {
           setErrorMessage(payload.error?.message);
          }
          

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

          // Compute processing duration when ingestion completes
          if (ui === "ready" && payload.created_at && payload.updated_at) {
            const created = new Date(payload.created_at).getTime();
            const updated = new Date(payload.updated_at).getTime();
            if (!isNaN(created) && !isNaN(updated) && updated > created) {
              setProcessingTime(formatDuration(updated - created));
            }
          }
          
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
    completedStages,
    chunks,
    awaitingProcessing: enabled && awaitingProcessing,
    processingTime,
    errorMessage, 
  };
}

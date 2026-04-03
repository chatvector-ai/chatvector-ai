"use client";

import { useEffect, useRef, useState } from "react";
import {
  DocumentNotFoundError,
  getDocumentStatus,
} from "../api";

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
    }
  }, [docKey]);

  useEffect(() => {
    if (!enabled || !documentId || !statusEndpoint) {
      return;
    }

    setAwaitingProcessing(true);

    let cancelled = false;
    const path = statusEndpoint;

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
      } catch (e) {
        if (e instanceof DocumentNotFoundError) {
          if (cancelled) return;
          setAwaitingProcessing(false);
          setPolledUiStatus("failed");
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
  }, [enabled, documentId, statusEndpoint]);

  return {
    status: polledUiStatus,
    stage,
    chunks,
    awaitingProcessing: enabled && awaitingProcessing,
  };
}

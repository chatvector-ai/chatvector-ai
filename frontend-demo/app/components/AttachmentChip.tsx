"use client";

import { FileText, X } from "lucide-react";
import { STAGE_LABELS } from "../lib/stageLabels";

type Props = {
  fileName: string;
  status: "processing" | "ready" | "failed";
  stage?: string;
  chunks?: { total: number; processed: number };
  awaitingProcessing?: boolean;
  queuePosition?: number;
  processingTime?: string;
  onRemove: () => void;
};

function chipLabel(
  fileName: string,
  status: Props["status"],
  stage: string | undefined,
  chunks: Props["chunks"],
  awaitingProcessing: boolean
): string {
  if (status === "ready") {
    return fileName;
  }
  if (status === "failed") {
    return STAGE_LABELS.failed;
  }
  if (awaitingProcessing && !stage) {
    return "Processing…";
  }
  const base =
    (stage && STAGE_LABELS[stage]) ||
    (stage ? stage : "Processing…");
  if (
    stage === "embedding" &&
    chunks != null &&
    typeof chunks.total === "number" &&
    chunks.total > 0
  ) {
    return `${STAGE_LABELS.embedding} (${chunks.total} chunks)`;
  }
  return base;
}

function iconAndTextClass(status: Props["status"]): string {
  if (status === "failed") return "text-red-400";
  if (status === "processing") return "text-amber-400";
  return "text-indigo-400";
}

export default function AttachmentChip({
  fileName,
  status,
  stage,
  chunks,
  awaitingProcessing = false,
  queuePosition,
  processingTime,
  onRemove,
}: Props) {
  const label = chipLabel(
    fileName,
    status,
    stage,
    chunks,
    awaitingProcessing
  );
  const tone = iconAndTextClass(status);

  // Surface the upload queue position only while the document waits its turn.
  // Once polling reports active progress (awaitingProcessing flips false) the
  // stage label takes over, and position 1 needs no indicator.
  const showQueuePosition =
    status === "processing" &&
    awaitingProcessing &&
    typeof queuePosition === "number" &&
    queuePosition > 1;

  return (
    <div className="flex w-fit max-w-full flex-col gap-0.5 rounded-lg border border-border bg-surface px-3 py-2">
      <div className="flex items-center gap-2">
        <FileText size={14} className={`shrink-0 ${tone}`} />
        <span className="shrink-0 text-xs text-muted">Active document:</span>
        <span
          className={`min-w-0 max-w-[min(100%,14rem)] truncate text-xs font-medium sm:max-w-[18rem] ${tone}`}
        >
          {label}
        </span>
        {status === "ready" && processingTime && (
          <span className="shrink-0 text-[10px] text-subtle" title={`Processed in ${processingTime}`}>
            {processingTime}
          </span>
        )}
        <button
          type="button"
          onClick={onRemove}
          className="shrink-0 rounded-md p-1 text-muted transition hover:bg-background hover:text-foreground"
          aria-label="Remove attachment"
        >
          <X size={16} />
        </button>
      </div>
      {showQueuePosition && (
        <span className="text-[10px] text-subtle">
          Position {queuePosition} in queue
        </span>
      )}
    </div>
  );
}

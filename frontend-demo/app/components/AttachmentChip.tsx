"use client";

import { FileText, X } from "lucide-react";
import { STAGE_LABELS } from "../lib/stageLabels";

type Props = {
  fileName: string;
  status: "processing" | "ready" | "failed";
  stage?: string;
  chunks?: { total: number; processed: number };
  awaitingProcessing?: boolean;
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

  return (
    <div className="px-4 py-2 bg-gray-900 border-t border-gray-800 flex items-center gap-2">
      <FileText size={14} className={tone} />
      <span className="text-xs text-gray-400">Active document:</span>
      <span
        className={`text-xs font-medium flex-1 truncate ${tone}`}
      >
        {label}
      </span>
      <button
        type="button"
        onClick={onRemove}
        className="p-1 rounded-md text-gray-500 hover:text-white hover:bg-gray-800 transition shrink-0"
        aria-label="Remove attachment"
      >
        <X size={16} />
      </button>
    </div>
  );
}

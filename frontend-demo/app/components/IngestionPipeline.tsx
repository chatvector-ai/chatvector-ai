"use client";

import { Check, Loader2, AlertCircle } from "lucide-react";
import { PIPELINE_STAGES, PIPELINE_STAGE_LABELS } from "../lib/stageLabels";

type StageState = "completed" | "active" | "pending" | "failed";

type Props = {
  /** Current in-progress stage key (e.g. "chunking"). Undefined while awaiting first event. */
  currentStage: string | undefined;
  /** Set of stage keys that have already finished. */
  completedStages: string[];
  /** Whether the overall ingestion failed. */
  failed?: boolean;
  /** Chunk info surfaced during embedding stage. */
  chunks?: { total: number; processed: number };
};

function getStageState(
  stageKey: string,
  currentStage: string | undefined,
  completedStages: string[],
  failed: boolean
): StageState {
  if (completedStages.includes(stageKey)) return "completed";
  if (stageKey === "completed" && currentStage === "completed" && !failed)
    return "completed";
  if (stageKey === currentStage) return failed ? "failed" : "active";
  return "pending";
}

function StageRow({
  stageKey,
  label,
  state,
  isLast,
  chunks,
}: {
  stageKey: string;
  label: string;
  state: StageState;
  isLast: boolean;
  chunks?: { total: number; processed: number };
}) {
  const showChunks =
    stageKey === "embedding" && state === "active" && chunks?.total;

  return (
    <li className="flex items-start gap-3">
      {/* Vertical connector + icon column */}
      <div className="flex flex-col items-center">
        <div
          className={[
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-full ring-1 transition-all duration-300",
            state === "completed"
              ? "bg-emerald-500/15 ring-emerald-400/40 text-emerald-400"
              : state === "active"
                ? "bg-blue/10 ring-blue/30 text-blue"
                : state === "failed"
                  ? "bg-red-500/10 ring-red-500/30 text-red-400"
                  : "bg-surface ring-border text-muted/40",
          ].join(" ")}
        >
          {state === "completed" && (
            <Check size={13} strokeWidth={2.5} aria-hidden />
          )}
          {state === "active" && (
            <Loader2 size={13} strokeWidth={2.5} className="animate-spin" aria-hidden />
          )}
          {state === "failed" && (
            <AlertCircle size={13} strokeWidth={2} aria-hidden />
          )}
          {state === "pending" && (
            <span className="h-1.5 w-1.5 rounded-full bg-muted/30" />
          )}
        </div>
        {!isLast && (
          <div
            className={[
              "mt-1 w-px flex-1 min-h-[1.25rem] transition-colors duration-500",
              state === "completed" ? "bg-emerald-400/25" : "bg-border/60",
            ].join(" ")}
          />
        )}
      </div>

      {/* Label */}
      <div className="pb-4 pt-0.5">
        <span
          className={[
            "text-sm font-medium leading-none transition-colors duration-200",
            state === "completed"
              ? "text-emerald-400"
              : state === "active"
                ? "text-foreground"
                : state === "failed"
                  ? "text-red-400"
                  : "text-muted/50",
          ].join(" ")}
        >
          {label}
        </span>
        {showChunks && (
          <p className="mt-1 text-xs text-muted">
            {chunks!.total} chunk{chunks!.total !== 1 ? "s" : ""}
          </p>
        )}
      </div>
    </li>
  );
}

export default function IngestionPipeline({
  currentStage,
  completedStages,
  failed = false,
  chunks,
}: Props) {
  return (
    <ul className="w-full" role="list" aria-label="Ingestion progress">
      {PIPELINE_STAGES.map((stageKey, idx) => {
        const state = getStageState(stageKey, currentStage, completedStages, failed);
        const label = PIPELINE_STAGE_LABELS[stageKey];
        const isLast = idx === PIPELINE_STAGES.length - 1;

        return (
          <StageRow
            key={stageKey}
            stageKey={stageKey}
            label={label}
            state={state}
            isLast={isLast}
            chunks={chunks}
          />
        );
      })}
    </ul>
  );
}

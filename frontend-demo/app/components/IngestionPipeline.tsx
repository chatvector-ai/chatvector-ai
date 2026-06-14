"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, AlertCircle } from "lucide-react";
import {
  formatChunkProgress,
  shouldShowChunkProgress,
} from "../lib/chunkProgress";
import { PIPELINE_STAGES, PIPELINE_STAGE_LABELS } from "../lib/stageLabels";

/** ms between each incremental stage completion when fast-forwarding. */
const STEP_MS = 380;

type StageState = "completed" | "active" | "pending" | "failed";

type Props = {
  /** Current in-progress stage key (e.g. "chunking"). Undefined while awaiting first event. */
  currentStage: string | undefined;
  /** Whether the overall ingestion failed. */
  failed?: boolean;
  /** Chunk info surfaced during embedding stage. */
  chunks?: { total: number; processed: number };
  /** Fires each time the animated displayed stage advances, including the final "completed" tick. */
  errorMessage?: string;
  onDisplayedStageChange?: (stage: string | undefined) => void;
};

/**
 * When the actual stage jumps ahead by multiple steps (rapid SSE updates),
 * this hook steps through each intermediate stage one at a time so each
 * completion animates in sequentially instead of teleporting.
 * When `instant` is true (e.g. on failure) it jumps directly without delays.
 */
function useAnimatedStage(actualStage: string | undefined, instant = false) {
  const [displayedIdx, setDisplayedIdx] = useState(-1);
  const displayedIdxRef = useRef(-1);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];

    const actualIdx =
      actualStage != null ? PIPELINE_STAGES.indexOf(actualStage as never) : -1;

    if (actualIdx < 0) {
      displayedIdxRef.current = -1;
      setDisplayedIdx(-1);
      return;
    }

    const fromIdx = displayedIdxRef.current;

    if (actualIdx <= fromIdx) return;

    if (instant) {
      displayedIdxRef.current = actualIdx;
      setDisplayedIdx(actualIdx);
      return;
    }

    const steps = actualIdx - fromIdx;
    for (let s = 1; s <= steps; s++) {
      const target = fromIdx + s;
      if (s === 1) {
        // Advance the first step synchronously so the active stage renders
        // on the very first paint with no visible delay.
        displayedIdxRef.current = target;
        setDisplayedIdx(target);
      } else {
        const t = setTimeout(
          () => {
            displayedIdxRef.current = target;
            setDisplayedIdx(target);
          },
          (s - 1) * STEP_MS
        );
        timersRef.current.push(t);
      }
    }

    return () => {
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
    };
  }, [actualStage, instant]);

  const displayedStage =
    displayedIdx >= 0 ? PIPELINE_STAGES[displayedIdx] : undefined;
  const displayedCompleted: string[] =
    displayedIdx > 0 ? Array.from(PIPELINE_STAGES.slice(0, displayedIdx)) : [];

  return { displayedStage, displayedCompleted };
}

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
  errorMessage,
}: {
  stageKey: string;
  label: string;
  state: StageState;
  isLast: boolean;
  chunks?: { total: number; processed: number };
  errorMessage?: string;
}) {
  const showChunks = shouldShowChunkProgress({ stageKey, state, chunks });
  const chunkProgressLabel =
    showChunks && chunks ? formatChunkProgress(chunks) : null;

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
      <div className="relative pb-4 pt-0.5">
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
        {chunkProgressLabel && (
          <p className="absolute top-full -mt-3 text-xs text-muted">
            {chunkProgressLabel}
          </p>
        )}
        {state === "failed" && errorMessage && (
          <p className="absolute top-full -mt-3 text-xs text-red-400/80">
            {errorMessage.slice(0, 80)}
          </p>
        )}
      </div>
    </li>
  );
}

export default function IngestionPipeline({
  currentStage,
  failed = false,
  chunks,
  errorMessage,
  onDisplayedStageChange,
}: Props) {
  const { displayedStage, displayedCompleted } = useAnimatedStage(currentStage, failed);

  const onDisplayedStageChangeRef = useRef(onDisplayedStageChange);
  onDisplayedStageChangeRef.current = onDisplayedStageChange;

  useEffect(() => {
    onDisplayedStageChangeRef.current?.(displayedStage);
  }, [displayedStage]);

  return (
    <ul className="w-full" role="list" aria-label="Ingestion progress">
      {PIPELINE_STAGES.map((stageKey, idx) => {
        const state = getStageState(stageKey, displayedStage, displayedCompleted, failed);
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
            errorMessage={state === "failed" ? errorMessage : undefined}  
          />
        );
      })}
    </ul>
  );
}

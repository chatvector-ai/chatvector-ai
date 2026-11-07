"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Loader2, AlertCircle } from "lucide-react";
import {
  formatChunkProgress,
  resolveStageForChunkAnimation,
  shouldShowChunkProgress,
} from "../lib/chunkProgress";
import { useAnimatedChunkCount } from "../lib/hooks/useAnimatedChunkCount";
import {
  PIPELINE_STAGES,
  PIPELINE_STAGE_LABELS,
  type PipelineStage,
} from "../lib/stageLabels";

/** ms between each incremental stage completion when fast-forwarding. */
const STEP_MS = 380;

const EMBEDDING_STAGE_INDEX = PIPELINE_STAGES.indexOf("embedding");
const RETRYING_STAGE_INDEX = PIPELINE_STAGES.indexOf("retrying");

type StageState = "completed" | "active" | "retrying" | "pending" | "failed";

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
  const lastNonRetryIdxRef = useRef(-1);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];

    const actualIdx =
      actualStage != null ? PIPELINE_STAGES.indexOf(actualStage as never) : -1;

    if (actualIdx < 0) {
      displayedIdxRef.current = -1;
      lastNonRetryIdxRef.current = -1;
      setDisplayedIdx(-1);
      return;
    }

    const fromIdx = displayedIdxRef.current;

    if (
      instant ||
      actualStage === "retrying" ||
      fromIdx === RETRYING_STAGE_INDEX
    ) {
      if (actualStage !== "retrying") {
        lastNonRetryIdxRef.current = actualIdx;
      }
      displayedIdxRef.current = actualIdx;
      setDisplayedIdx(actualIdx);
      return;
    }

    if (actualIdx <= fromIdx) return;

    const targets: number[] = [];
    for (let idx = fromIdx + 1; idx <= actualIdx; idx++) {
      if (PIPELINE_STAGES[idx] !== "retrying") {
        targets.push(idx);
      }
    }

    targets.forEach((target, stepIndex) => {
      if (stepIndex === 0) {
        // Advance the first step synchronously so the active stage renders
        // on the very first paint with no visible delay.
        displayedIdxRef.current = target;
        lastNonRetryIdxRef.current = target;
        setDisplayedIdx(target);
      } else {
        const t = setTimeout(
          () => {
            displayedIdxRef.current = target;
            lastNonRetryIdxRef.current = target;
            setDisplayedIdx(target);
          },
          stepIndex * STEP_MS
        );
        timersRef.current.push(t);
      }
    });

    return () => {
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
    };
  }, [actualStage, instant]);

  const displayedStage =
    displayedIdx >= 0 ? PIPELINE_STAGES[displayedIdx] : undefined;
  const completedUpperBound =
    displayedStage === "retrying" ? lastNonRetryIdxRef.current : displayedIdx;
  const displayedCompleted: string[] =
    completedUpperBound > 0
      ? PIPELINE_STAGES.slice(0, completedUpperBound).filter(
          (stage) => stage !== "retrying"
        )
      : [];

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
  if (stageKey === currentStage) {
    if (failed) return "failed";
    if (stageKey === "retrying") return "retrying";
    return "active";
  }
  return "pending";
}

function StageRow({
  stageKey,
  label,
  state,
  isLast,
  displayChunks,
  errorMessage,
}: {
  stageKey: string;
  label: string;
  state: StageState;
  isLast: boolean;
  displayChunks?: { total: number; processed: number };
  errorMessage?: string;
}) {
  const showChunks = shouldShowChunkProgress({
    stageKey,
    state,
    chunks: displayChunks,
  });
  const chunkProgressLabel =
    showChunks && displayChunks
      ? formatChunkProgress(displayChunks)
      : null;

  return (
    <li
      data-stage={stageKey}
      data-stage-state={state}
      className="flex items-start gap-3"
    >
      {/* Vertical connector + icon column */}
      <div className="flex flex-col items-center">
        <div
          className={[
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-full ring-1 transition-all duration-300",
            state === "completed"
              ? "bg-success/15 ring-success/35 text-success"
              : state === "active"
                ? "bg-accent/15 ring-accent/40 text-accent"
                : state === "retrying"
                  ? "bg-amber-500/15 ring-amber-500/40 text-amber-400"
                  : state === "failed"
                    ? "bg-danger/10 ring-danger/30 text-danger"
                    : "bg-surface ring-border text-muted/40",
          ].join(" ")}
        >
          {state === "completed" && (
            <Check size={13} strokeWidth={2.5} aria-hidden />
          )}
          {(state === "active" || state === "retrying") && (
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
              state === "completed" ? "bg-success/25" : "bg-border/60",
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
              ? "text-success-text"
              : state === "active"
                ? "text-accent-text"
                : state === "retrying"
                  ? "text-amber-400"
                  : state === "failed"
                    ? "text-danger-text"
                    : "text-muted/50",
          ].join(" ")}
        >
          {label}
        </span>
        {chunkProgressLabel && (
          <p className="absolute top-full -mt-3 whitespace-nowrap text-xs tabular-nums text-muted">
            {chunkProgressLabel}
          </p>
        )}
        {state === "failed" && errorMessage && (
          <p className="absolute top-full -mt-3 text-xs text-danger-text/80">
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
  const peakProcessedRef = useRef(0);

  if (chunks) {
    if (chunks.processed === 0) {
      peakProcessedRef.current = 0;
    } else {
      peakProcessedRef.current = Math.max(peakProcessedRef.current, chunks.processed);
    }
  }

  const currentStageIndex = currentStage
    ? PIPELINE_STAGES.indexOf(currentStage as never)
    : -1;

  const chunkCountTarget =
    chunks?.processed ??
    (peakProcessedRef.current > 0 && currentStageIndex >= EMBEDDING_STAGE_INDEX
      ? peakProcessedRef.current
      : undefined);

  const animatedProcessed = useAnimatedChunkCount(
    chunkCountTarget !== undefined && currentStageIndex >= EMBEDDING_STAGE_INDEX
      ? chunkCountTarget
      : undefined
  );

  const stageForAnimation = resolveStageForChunkAnimation({
    currentStage,
    animatedProcessed,
    chunkTarget: peakProcessedRef.current,
    failed,
    pipelineStages: PIPELINE_STAGES,
  });

  const { displayedStage, displayedCompleted } = useAnimatedStage(
    stageForAnimation,
    failed
  );

  const displayChunks =
    chunks && animatedProcessed !== undefined
      ? { total: chunks.total, processed: animatedProcessed }
      : chunks;

  const onDisplayedStageChangeRef = useRef(onDisplayedStageChange);
  onDisplayedStageChangeRef.current = onDisplayedStageChange;

  useEffect(() => {
    onDisplayedStageChangeRef.current?.(displayedStage);
  }, [displayedStage]);

  const happyPathStages: PipelineStage[] = PIPELINE_STAGES.filter(
    (stageKey) => stageKey !== "retrying"
  );
  const visibleStages: PipelineStage[] =
    displayedStage === "retrying"
      ? (() => {
          const stages: PipelineStage[] = [...happyPathStages];
          const inProgressIdx = Math.min(
            displayedCompleted.length,
            stages.length - 2
          );
          stages.splice(inProgressIdx, 1, "retrying");
          return stages;
        })()
      : happyPathStages;

  return (
    <ul className="w-full" role="list" aria-label="Ingestion progress">
      {visibleStages.map((stageKey, idx) => {
        const state = getStageState(stageKey, displayedStage, displayedCompleted, failed);
        const label = PIPELINE_STAGE_LABELS[stageKey];
        const isLast = idx === visibleStages.length - 1;

        return (
          <StageRow
            key={stageKey}
            stageKey={stageKey}
            label={label}
            state={state}
            isLast={isLast}
            displayChunks={displayChunks}
            errorMessage={state === "failed" ? errorMessage : undefined}
          />
        );
      })}
    </ul>
  );
}

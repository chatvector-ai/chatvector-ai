export type ChunkProgress = {
  total: number;
  processed: number;
};

type ChunkProgressStageState =
  | "completed"
  | "active"
  | "retrying"
  | "pending"
  | "failed";

const EMBEDDING_STAGE = "embedding";

export function formatChunkProgress(chunks: ChunkProgress) {
  return `${chunks.processed} / ${chunks.total}`;
}

/** Hold the pipeline on embedding until the odometer reaches the latest target. */
export function resolveStageForChunkAnimation({
  currentStage,
  animatedProcessed,
  chunkTarget,
  failed,
  pipelineStages,
}: {
  currentStage: string | undefined;
  animatedProcessed: number | undefined;
  chunkTarget: number;
  failed: boolean;
  pipelineStages: readonly string[];
}): string | undefined {
  if (currentStage === "retrying") {
    return currentStage;
  }
  const embeddingIdx = pipelineStages.indexOf(EMBEDDING_STAGE);
  const currentIdx = currentStage ? pipelineStages.indexOf(currentStage) : -1;
  const stillCounting =
    chunkTarget > 0 &&
    animatedProcessed !== undefined &&
    animatedProcessed < chunkTarget;

  if (!failed && currentIdx > embeddingIdx && stillCounting) {
    return EMBEDDING_STAGE;
  }

  return currentStage;
}

export function shouldShowChunkProgress({
  stageKey,
  state,
  chunks,
}: {
  stageKey: string;
  state: ChunkProgressStageState;
  chunks?: ChunkProgress;
}) {
  return (
    stageKey === "embedding" &&
    state === "active" &&
    !!chunks &&
    chunks.total > 0
  );
}

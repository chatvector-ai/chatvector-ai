export type ChunkProgress = {
  total: number;
  processed: number;
};

type ChunkProgressStageState = "completed" | "active" | "pending" | "failed";

export function formatChunkProgress(chunks: ChunkProgress) {
  const chunkLabel = chunks.total === 1 ? "chunk" : "chunks";
  return `${chunks.processed} / ${chunks.total} ${chunkLabel}`;
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

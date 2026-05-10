export const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  uploaded: "Uploaded",
  extracting: "Extracting text",
  chunking: "Chunking",
  embedding: "Embedding",
  storing: "Storing",
  completed: "Ready",
  failed: "Failed",
};

/**
 * Ordered list of pipeline stages as they progress on the backend.
 * "uploading" is a synthetic client-side stage prepended before server stages begin.
 */
export const PIPELINE_STAGES = [
  "uploading",
  "queued",
  "extracting",
  "chunking",
  "embedding",
  "storing",
  "completed",
] as const;

export type PipelineStage = (typeof PIPELINE_STAGES)[number];

export const PIPELINE_STAGE_LABELS: Record<PipelineStage, string> = {
  uploading: "Uploading",
  queued: "Queued",
  extracting: "Extracting text",
  chunking: "Chunking",
  embedding: "Embedding",
  storing: "Storing",
  completed: "Ready",
};

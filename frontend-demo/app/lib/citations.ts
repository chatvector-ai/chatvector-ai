import type { ChatSource, RetrievalInspectorData } from "./api";

export function deduplicatedSources(sources: ChatSource[]): ChatSource[] {
  const seen = new Set<string>();
  return sources.filter((source) => {
    const key = `${source.file_name}::${source.page_number ?? "null"}::${source.chunk_index ?? "null"}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function formatCitationLine(source: ChatSource): string {
  const parts = [source.file_name];
  if (source.page_number != null) {
    parts.push(`p.${source.page_number}`);
  }
  if (source.chunk_index != null) {
    parts.push(`chunk ${source.chunk_index}`);
  }
  let line = parts.join(" · ");
  if (source.score != null) {
    line += ` · score ${source.score.toFixed(2)}`;
  }
  return line;
}

export function formatLatencySeconds(latencyMs: number): string {
  if (latencyMs < 1000) {
    return `${latencyMs}ms`;
  }
  return `${(latencyMs / 1000).toFixed(1)}s`;
}

export function formatResponseMetadata(options: {
  chunks?: number;
  model?: string;
  latency_ms?: number;
}): string | null {
  const parts: string[] = [];
  if (options.chunks !== undefined) {
    parts.push(`${options.chunks} chunk${options.chunks === 1 ? "" : "s"}`);
  }
  if (options.model) {
    parts.push(options.model);
  }
  if (options.latency_ms !== undefined) {
    parts.push(formatLatencySeconds(options.latency_ms));
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

export type InspectorSourceField = {
  label: string;
  value: string;
};

export function hasInspectableRetrievalData(data: RetrievalInspectorData): boolean {
  if (data.question) return true;
  if (data.retrieval_debug) {
    const debug = data.retrieval_debug;
    if (debug.original_query) return true;
    if (debug.transformation_strategy) return true;
    if (debug.transformed_queries && debug.transformed_queries.length > 0) {
      return true;
    }
  }
  if (data.sources && data.sources.length > 0) return true;
  if (data.chunks !== undefined) return true;
  if (data.model) return true;
  if (data.latency_ms !== undefined) return true;
  return false;
}

export function inspectorSourceFields(source: ChatSource): InspectorSourceField[] {
  const fields: InspectorSourceField[] = [
    { label: "File", value: source.file_name },
  ];
  if (source.page_number != null) {
    fields.push({ label: "Page", value: String(source.page_number) });
  }
  if (source.chunk_index != null) {
    fields.push({ label: "Chunk", value: String(source.chunk_index) });
  }
  if (source.score != null) {
    fields.push({ label: "Score", value: source.score.toFixed(2) });
  }
  if (source.score_type) {
    fields.push({ label: "Score type", value: source.score_type });
  }
  return fields;
}

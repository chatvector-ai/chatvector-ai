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

export function formatSourceCitation(source: ChatSource): string {
  const parts = [source.file_name];
  if (source.page_number != null) {
    parts.push(`p.${source.page_number}`);
  }
  if (source.chunk_index != null) {
    parts.push(`chunk ${source.chunk_index}`);
  }
  return parts.join(" · ");
}

export function formatCitationSummary(sources?: ChatSource[]): string | null {
  if (!sources || sources.length === 0) {
    return null;
  }
  const unique = deduplicatedSources(sources);
  if (unique.length === 0) {
    return null;
  }
  return unique.map(formatSourceCitation).join(" · ");
}

export function formatCitationLine(source: ChatSource): string {
  let line = formatSourceCitation(source);
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
    if (debug.history_resolution_applied === true) return true;
    if (debug.history_resolution_skipped_reason) return true;
    if (debug.history_resolution_fallback_reason) return true;
    if (debug.history_resolved_query) return true;
    if (debug.effective_retrieval_query) return true;
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
  if (source.vector_score != null) {
    fields.push({ label: "Vector score", value: source.vector_score.toFixed(2) });
  }
  if (source.full_text_score != null) {
    fields.push({
      label: "Full-text score",
      value: source.full_text_score.toFixed(2),
    });
  }
  if (source.rrf_score != null) {
    fields.push({ label: "RRF score", value: source.rrf_score.toFixed(2) });
  }
  if (source.reranker_score != null) {
    fields.push({
      label: "Reranker score",
      value: source.reranker_score.toFixed(2),
    });
  }
  if (source.rerank_order != null) {
    fields.push({ label: "Rerank order", value: String(source.rerank_order) });
  }
  return fields;
}

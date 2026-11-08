import type { ChatSource, RetrievalInspectorData } from "./api";

function formatPageLocation(
  source: Pick<ChatSource, "page_number" | "page_end">,
): string | null {
  const { page_number, page_end } = source;
  if (page_number == null) {
    return null;
  }
  if (page_end == null || page_end === page_number) {
    return `p.${page_number}`;
  }
  return `p.${page_number}-${page_end}`;
}

export function deduplicatedSources(sources: ChatSource[]): ChatSource[] {
  const seen = new Set<string>();
  return sources.filter((source) => {
    const key = `${source.file_name}::${source.page_number ?? "null"}::${source.page_end ?? "null"}::${source.chunk_index ?? "null"}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function formatSourceCitation(source: ChatSource): string {
  const parts = [source.file_name];
  const page = formatPageLocation(source);
  if (page != null) {
    parts.push(page);
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

const RANKING_SCORE_LABELS: Record<string, string> = {
  vector: "Vector similarity score",
  hybrid_rrf: "Hybrid RRF score",
  reranked: "Reranked score",
};

const TIMING_STAGE_ORDER = [
  "transform",
  "embed",
  "search",
  "rerank",
  "context",
  "total",
] as const;

const TIMING_STAGE_LABELS: Record<string, string> = {
  transform: "Transform",
  embed: "Embed",
  search: "Search",
  rerank: "Rerank",
  context: "Context",
  total: "Retrieval total",
};

const PACKED_CONTEXT_KEYS = [
  "packed_chunks",
  "selected_context",
  "selected_context_chunks",
] as const;

function humanizeConfigFieldName(name: string): string {
  return name
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatConfigScalar(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatEffectiveConfigEntry(entry: unknown): string | null {
  if (entry == null || typeof entry !== "object" || Array.isArray(entry)) {
    return null;
  }
  const record = entry as Record<string, unknown>;
  if (!("value" in record)) {
    return null;
  }
  const valueText = formatConfigScalar(record.value);
  if (typeof record.source === "string" && record.source.length > 0) {
    return `${valueText} (${record.source})`;
  }
  return valueText;
}

export function rankingScoreFieldLabel(
  scoreType: string | null | undefined,
): string {
  if (scoreType && RANKING_SCORE_LABELS[scoreType]) {
    return RANKING_SCORE_LABELS[scoreType];
  }
  if (scoreType) {
    return `${scoreType} score`;
  }
  return "Ranking score";
}

export function inspectorEffectiveConfigFields(
  effectiveConfig: Record<string, unknown>,
): InspectorSourceField[] {
  const fields: InspectorSourceField[] = [];
  const names = Object.keys(effectiveConfig).sort();
  for (const name of names) {
    const formatted = formatEffectiveConfigEntry(effectiveConfig[name]);
    if (formatted === null) continue;
    fields.push({
      label: humanizeConfigFieldName(name),
      value: formatted,
    });
  }
  return fields;
}

export function inspectorScopeField(
  effectiveConfig: Record<string, unknown> | undefined,
): InspectorSourceField | null {
  if (!effectiveConfig?.scope) return null;
  const formatted = formatEffectiveConfigEntry(effectiveConfig.scope);
  if (formatted === null) return null;
  return { label: "Scope", value: formatted };
}

export function inspectorMetadataFilterField(
  effectiveConfig: Record<string, unknown> | undefined,
): InspectorSourceField | null {
  if (!effectiveConfig?.metadata_filter) return null;
  const formatted = formatEffectiveConfigEntry(effectiveConfig.metadata_filter);
  if (formatted === null) return null;
  return { label: "Metadata filter", value: formatted };
}

export function inspectorRerankerFields(
  reranker: Record<string, unknown>,
): InspectorSourceField[] {
  const fields: InspectorSourceField[] = [];
  const provider = reranker.provider;
  if (typeof provider === "string" && provider.length > 0) {
    fields.push({ label: "Provider", value: provider });
  }
  const model = reranker.model;
  if (typeof model === "string" && model.length > 0) {
    fields.push({ label: "Model", value: model });
  }
  const fallback = reranker.fallback_reason;
  if (typeof fallback === "string" && fallback.length > 0) {
    fields.push({ label: "Fallback reason", value: fallback });
  }
  return fields;
}

export function inspectorTimingStageFields(
  timingMs: Record<string, number>,
): InspectorSourceField[] {
  const fields: InspectorSourceField[] = [];
  for (const stage of TIMING_STAGE_ORDER) {
    const value = timingMs[stage];
    if (value === undefined) continue;
    fields.push({
      label: TIMING_STAGE_LABELS[stage] ?? humanizeConfigFieldName(stage),
      value: formatLatencySeconds(value),
    });
  }
  for (const stage of Object.keys(timingMs).sort()) {
    if ((TIMING_STAGE_ORDER as readonly string[]).includes(stage)) continue;
    const value = timingMs[stage];
    if (value === undefined) continue;
    fields.push({
      label: humanizeConfigFieldName(stage),
      value: formatLatencySeconds(value),
    });
  }
  return fields;
}

export function packedContextFromDebug(
  debug: Record<string, unknown> | undefined,
): unknown[] | null {
  if (!debug) return null;
  for (const key of PACKED_CONTEXT_KEYS) {
    const value = debug[key];
    if (Array.isArray(value) && value.length > 0) {
      return value;
    }
  }
  return null;
}

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
    if (
      debug.effective_config &&
      typeof debug.effective_config === "object" &&
      !Array.isArray(debug.effective_config) &&
      Object.keys(debug.effective_config).length > 0
    ) {
      return true;
    }
    if (typeof debug.resolved_preset === "string" && debug.resolved_preset) {
      return true;
    }
    if (
      debug.reranker &&
      typeof debug.reranker === "object" &&
      !Array.isArray(debug.reranker)
    ) {
      return true;
    }
    if (
      debug.timing_ms &&
      typeof debug.timing_ms === "object" &&
      !Array.isArray(debug.timing_ms) &&
      Object.keys(debug.timing_ms).length > 0
    ) {
      return true;
    }
    if (packedContextFromDebug(debug as Record<string, unknown>)) return true;
  }
  if (data.sources && data.sources.length > 0) return true;
  if (data.chunks !== undefined) return true;
  if (data.model) return true;
  if (data.latency_ms !== undefined) return true;
  if (data.request_latency_ms !== undefined) return true;
  return false;
}

export function inspectorSourceFields(source: ChatSource): InspectorSourceField[] {
  const fields: InspectorSourceField[] = [
    { label: "File", value: source.file_name },
  ];
  const page = formatPageLocation(source);
  if (page != null) {
    fields.push({
      label:
        source.page_end != null && source.page_end !== source.page_number
          ? "Pages"
          : "Page",
      value:
        source.page_end != null && source.page_end !== source.page_number
          ? `${source.page_number}-${source.page_end}`
          : String(source.page_number),
    });
  }
  if (source.chunk_index != null) {
    fields.push({ label: "Chunk", value: String(source.chunk_index) });
  }
  if (source.score != null) {
    fields.push({
      label: rankingScoreFieldLabel(source.score_type),
      value: source.score.toFixed(2),
    });
  }
  if (source.vector_score != null) {
    fields.push({
      label: "Vector similarity",
      value: source.vector_score.toFixed(2),
    });
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

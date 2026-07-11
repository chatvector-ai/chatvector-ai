import type { ChatSource } from "./api";

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

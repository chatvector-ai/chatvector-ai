"use client";

import { useState } from "react";
import type { ChatSource, RetrievalInspectorData } from "../lib/api";
import {
  deduplicatedSources,
  formatLatencySeconds,
  hasInspectableRetrievalData,
  inspectorEffectiveConfigFields,
  inspectorMetadataFilterField,
  inspectorRerankerFields,
  inspectorScopeField,
  inspectorSourceFields,
  inspectorTimingStageFields,
  packedContextFromDebug,
} from "../lib/citations";

type Props = {
  data: RetrievalInspectorData;
};

function InspectorRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[minmax(0,7rem)_1fr] gap-x-3 gap-y-0.5 sm:grid-cols-[minmax(0,9rem)_1fr]">
      <dt className="text-muted">{label}</dt>
      <dd className="break-words text-foreground">{value}</dd>
    </div>
  );
}

function packedContextItemLabel(item: unknown, index: number): string {
  if (item != null && typeof item === "object" && !Array.isArray(item)) {
    const record = item as Record<string, unknown>;
    const fileName =
      typeof record.file_name === "string" ? record.file_name : null;
    if (fileName) {
      const parts = [fileName];
      if (record.page_number != null) {
        parts.push(`p.${String(record.page_number)}`);
      }
      if (record.chunk_index != null) {
        parts.push(`chunk ${String(record.chunk_index)}`);
      }
      return parts.join(" · ");
    }
  }
  if (typeof item === "string") return item;
  return `Item ${index + 1}`;
}

export default function RetrievalInspector({ data }: Props) {
  const [isOpen, setIsOpen] = useState(false);

  if (!hasInspectableRetrievalData(data)) {
    return null;
  }

  const debug = data.retrieval_debug;
  const debugRecord = debug as Record<string, unknown> | undefined;
  const effectiveConfig =
    debug?.effective_config &&
    typeof debug.effective_config === "object" &&
    !Array.isArray(debug.effective_config)
      ? (debug.effective_config as Record<string, unknown>)
      : undefined;
  const reranker =
    debug?.reranker &&
    typeof debug.reranker === "object" &&
    !Array.isArray(debug.reranker)
      ? (debug.reranker as Record<string, unknown>)
      : undefined;
  const timingMs =
    debug?.timing_ms &&
    typeof debug.timing_ms === "object" &&
    !Array.isArray(debug.timing_ms)
      ? (debug.timing_ms as Record<string, number>)
      : undefined;
  const sources = data.sources ? deduplicatedSources(data.sources) : [];
  const scopeField = inspectorScopeField(effectiveConfig);
  const metadataFilterField = inspectorMetadataFilterField(effectiveConfig);
  const effectiveConfigFields = effectiveConfig
    ? inspectorEffectiveConfigFields(effectiveConfig).filter(
        (field) => field.label !== "Scope" && field.label !== "Metadata Filter",
      )
    : [];
  const rerankerFields = reranker ? inspectorRerankerFields(reranker) : [];
  const timingStageFields = timingMs ? inspectorTimingStageFields(timingMs) : [];
  const packedContext = packedContextFromDebug(debugRecord);
  const resolvedPreset =
    typeof debug?.resolved_preset === "string" && debug.resolved_preset
      ? debug.resolved_preset
      : null;

  const hasQuerySection = Boolean(
    data.question ||
      debug?.original_query ||
      debug?.transformation_strategy ||
      (debug?.transformed_queries && debug.transformed_queries.length > 0) ||
      debug?.history_resolution_applied === true ||
      debug?.history_resolution_skipped_reason ||
      debug?.history_resolution_fallback_reason ||
      debug?.history_resolved_query ||
      debug?.effective_retrieval_query
  );

  const hasTimingsSection = Boolean(
    timingStageFields.length > 0 ||
      data.latency_ms !== undefined ||
      data.request_latency_ms !== undefined
  );

  return (
    <details
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      className="mt-2 rounded-lg border border-border bg-background/40 text-xs"
    >
      <summary
        onClick={(event) => {
          event.preventDefault();
          setIsOpen((prev) => !prev);
        }}
        className="cursor-pointer list-none px-3 py-2 text-muted transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden"
      >
        <span className="font-medium">Retrieval inspector</span>
        <span className="ml-1.5 font-normal text-muted/80">(developer)</span>
      </summary>
      {isOpen && (
        <div className="space-y-3 border-t border-border px-3 py-3">
        {hasQuerySection && (
          <section aria-label="Query">
            <h4 className="mb-1.5 font-medium text-foreground">Query</h4>
            <dl className="space-y-1">
              {data.question && (
                <InspectorRow label="Original" value={data.question} />
              )}
              {!data.question && debug?.original_query && (
                <InspectorRow label="Original" value={debug.original_query} />
              )}
              {debug?.transformation_strategy && (
                <InspectorRow
                  label="Strategy"
                  value={debug.transformation_strategy}
                />
              )}
              {debug?.history_resolution_applied === true && (
                <InspectorRow label="History" value="Ran" />
              )}
              {debug?.history_resolution_skipped_reason && (
                <InspectorRow
                  label="History"
                  value={`Skipped (${debug.history_resolution_skipped_reason})`}
                />
              )}
              {debug?.history_resolution_fallback_reason && (
                <InspectorRow
                  label="History"
                  value={`Fallback (${debug.history_resolution_fallback_reason})`}
                />
              )}
              {debug?.history_resolved_query && (
                <InspectorRow
                  label="Resolved query"
                  value={debug.history_resolved_query}
                />
              )}
              {debug?.effective_retrieval_query && (
                <InspectorRow
                  label="Searched query"
                  value={debug.effective_retrieval_query}
                />
              )}
            </dl>
            {debug?.transformed_queries &&
              debug.transformed_queries.length > 0 && (
                <div className="mt-2">
                  <p className="mb-1 text-muted">Transformed queries</p>
                  <ol className="list-decimal space-y-1 pl-4 text-foreground">
                    {debug.transformed_queries.map((query, index) => (
                      <li key={index} className="break-words">
                        {query}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
          </section>
        )}

        {(resolvedPreset || effectiveConfigFields.length > 0) && (
          <section aria-label="Effective config">
            <h4 className="mb-1.5 font-medium text-foreground">
              Effective config
            </h4>
            <dl className="space-y-1">
              {resolvedPreset && (
                <InspectorRow label="Preset" value={resolvedPreset} />
              )}
              {effectiveConfigFields.map((field) => (
                <InspectorRow
                  key={field.label}
                  label={field.label}
                  value={field.value}
                />
              ))}
            </dl>
          </section>
        )}

        {(scopeField || metadataFilterField) && (
          <section aria-label="Scope and filter">
            <h4 className="mb-1.5 font-medium text-foreground">
              Scope and filter
            </h4>
            <dl className="space-y-1">
              {scopeField && (
                <InspectorRow label={scopeField.label} value={scopeField.value} />
              )}
              {metadataFilterField && (
                <InspectorRow
                  label={metadataFilterField.label}
                  value={metadataFilterField.value}
                />
              )}
            </dl>
          </section>
        )}

        {sources.length > 0 && (
          <section aria-label="Chunks">
            <h4 className="mb-1.5 font-medium text-foreground">
              Chunks ({sources.length})
            </h4>
            <ul className="space-y-2">
              {sources.map((source, index) => (
                <li
                  key={`${source.file_name}-${source.page_number ?? "na"}-${source.chunk_index ?? "na"}-${index}`}
                  className="rounded-md border border-border bg-surface/60 px-2.5 py-2"
                >
                  <dl className="space-y-1">
                    {inspectorSourceFields(source).map((field) => (
                      <InspectorRow
                        key={field.label}
                        label={field.label}
                        value={field.value}
                      />
                    ))}
                  </dl>
                </li>
              ))}
            </ul>
          </section>
        )}

        {packedContext && (
          <section aria-label="Packed context">
            <h4 className="mb-1.5 font-medium text-foreground">
              Packed context ({packedContext.length})
            </h4>
            <ol className="list-decimal space-y-1 pl-4 text-foreground">
              {packedContext.map((item, index) => {
                if (
                  item != null &&
                  typeof item === "object" &&
                  !Array.isArray(item)
                ) {
                  const source = item as ChatSource;
                  if (typeof source.file_name === "string") {
                    return (
                      <li key={index} className="rounded-md border border-border bg-surface/60 px-2.5 py-2">
                        <dl className="space-y-1">
                          {inspectorSourceFields(source).map((field) => (
                            <InspectorRow
                              key={field.label}
                              label={field.label}
                              value={field.value}
                            />
                          ))}
                        </dl>
                      </li>
                    );
                  }
                }
                return (
                  <li key={index} className="break-words">
                    {packedContextItemLabel(item, index)}
                  </li>
                );
              })}
            </ol>
          </section>
        )}

        {rerankerFields.length > 0 && (
          <section aria-label="Rerank">
            <h4 className="mb-1.5 font-medium text-foreground">Rerank</h4>
            <dl className="space-y-1">
              {rerankerFields.map((field) => (
                <InspectorRow
                  key={field.label}
                  label={field.label}
                  value={field.value}
                />
              ))}
            </dl>
          </section>
        )}

        {hasTimingsSection && (
          <section aria-label="Timings">
            <h4 className="mb-1.5 font-medium text-foreground">Timings</h4>
            <dl className="space-y-1">
              {timingStageFields.map((field) => (
                <InspectorRow
                  key={field.label}
                  label={field.label}
                  value={field.value}
                />
              ))}
              {data.latency_ms !== undefined && (
                <InspectorRow
                  label="Generation latency"
                  value={formatLatencySeconds(data.latency_ms)}
                />
              )}
              {data.request_latency_ms !== undefined && (
                <InspectorRow
                  label="Request latency"
                  value={formatLatencySeconds(data.request_latency_ms)}
                />
              )}
            </dl>
          </section>
        )}

        {(data.chunks !== undefined || data.model) && (
          <section aria-label="Response metadata">
            <h4 className="mb-1.5 font-medium text-foreground">Response</h4>
            <dl className="space-y-1">
              {data.chunks !== undefined && (
                <InspectorRow
                  label="Chunks"
                  value={`${data.chunks} retrieved`}
                />
              )}
              {data.model && <InspectorRow label="Model" value={data.model} />}
            </dl>
          </section>
        )}
        </div>
      )}
    </details>
  );
}

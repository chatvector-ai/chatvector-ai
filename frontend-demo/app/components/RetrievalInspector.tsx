"use client";

import { useState } from "react";
import type { RetrievalInspectorData } from "../lib/api";
import {
  deduplicatedSources,
  formatLatencySeconds,
  hasInspectableRetrievalData,
  inspectorSourceFields,
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

export default function RetrievalInspector({ data }: Props) {
  const [isOpen, setIsOpen] = useState(false);

  if (!hasInspectableRetrievalData(data)) {
    return null;
  }

  const debug = data.retrieval_debug;
  const sources = data.sources ? deduplicatedSources(data.sources) : [];
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

        {sources.length > 0 && (
          <section aria-label="Sources">
            <h4 className="mb-1.5 font-medium text-foreground">
              Sources ({sources.length})
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

        {(data.chunks !== undefined || data.model || data.latency_ms !== undefined) && (
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
              {data.latency_ms !== undefined && (
                <InspectorRow
                  label="Latency"
                  value={formatLatencySeconds(data.latency_ms)}
                />
              )}
            </dl>
          </section>
        )}
        </div>
      )}
    </details>
  );
}

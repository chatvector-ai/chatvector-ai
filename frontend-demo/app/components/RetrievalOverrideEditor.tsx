"use client";

import type { ReactNode } from "react";
import {
  MAX_MATCH_COUNT,
  MIN_MATCH_COUNT,
} from "../lib/retrievalSettings";
import {
  clearRetrievalOverride,
  createEmptyRetrievalOverrideDraft,
  isRetrievalOverrideExplicit,
  setRetrievalOverride,
  type QueryTransformationStrategy,
  type RerankerProvider,
  type RetrievalOverrideDraft,
} from "../lib/retrievalRequestOverrides";

type Props = {
  title: string;
  draft: RetrievalOverrideDraft;
  onChange: (draft: RetrievalOverrideDraft) => void;
  disabled?: boolean;
};

const TRANSFORM_STRATEGIES: QueryTransformationStrategy[] = [
  "rewrite",
  "expand",
  "stepback",
  "none",
];

function OverrideToggle({
  label,
  checked,
  onChange,
  disabled,
  children,
}: {
  label: string;
  checked: boolean;
  onChange: (enabled: boolean) => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-foreground">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          disabled={disabled}
          className="h-3.5 w-3.5 accent-[color:var(--accent)]"
        />
        <span className="font-medium">{label}</span>
      </label>
      {checked ? children : null}
    </div>
  );
}

export function emptyRetrievalOverrideDraft(): RetrievalOverrideDraft {
  return createEmptyRetrievalOverrideDraft();
}

export default function RetrievalOverrideEditor({
  title,
  draft,
  onChange,
  disabled = false,
}: Props) {
  const matchExplicit = isRetrievalOverrideExplicit(draft, "match_count");
  const hybridExplicit = isRetrievalOverrideExplicit(draft, "hybrid_enabled");
  const rerankExplicit = isRetrievalOverrideExplicit(draft, "reranking_enabled");
  const providerExplicit = isRetrievalOverrideExplicit(draft, "reranker_provider");
  const transformExplicit = isRetrievalOverrideExplicit(
    draft,
    "query_transformation_enabled",
  );
  const strategyExplicit = isRetrievalOverrideExplicit(
    draft,
    "query_transformation_strategy",
  );
  const historyAwareExplicit = isRetrievalOverrideExplicit(
    draft,
    "history_aware_retrieval",
  );
  const retrievalWindowExplicit = isRetrievalOverrideExplicit(
    draft,
    "retrieval_history_window",
  );
  const generationWindowExplicit = isRetrievalOverrideExplicit(
    draft,
    "generation_history_window",
  );

  const matchValue =
    typeof draft.explicit.match_count === "number"
      ? draft.explicit.match_count
      : MIN_MATCH_COUNT + 4;

  const hybridValue =
    typeof draft.explicit.hybrid_enabled === "boolean"
      ? draft.explicit.hybrid_enabled
      : false;

  const rerankValue =
    typeof draft.explicit.reranking_enabled === "boolean"
      ? draft.explicit.reranking_enabled
      : false;

  const providerValue =
    typeof draft.explicit.reranker_provider === "string"
      ? (draft.explicit.reranker_provider as RerankerProvider)
      : "similarity";

  const transformValue =
    typeof draft.explicit.query_transformation_enabled === "boolean"
      ? draft.explicit.query_transformation_enabled
      : false;

  const strategyValue =
    typeof draft.explicit.query_transformation_strategy === "string"
      ? (draft.explicit.query_transformation_strategy as QueryTransformationStrategy)
      : "rewrite";

  const historyAwareValue =
    typeof draft.explicit.history_aware_retrieval === "boolean"
      ? draft.explicit.history_aware_retrieval
      : false;

  const retrievalWindowValue =
    typeof draft.explicit.retrieval_history_window === "number"
      ? draft.explicit.retrieval_history_window
      : 0;

  const generationWindowValue =
    typeof draft.explicit.generation_history_window === "number"
      ? draft.explicit.generation_history_window
      : 0;

  return (
    <details
      open
      className="rounded-lg border border-border bg-background/40 text-xs"
    >
      <summary className="cursor-pointer list-none px-3 py-2 font-medium text-foreground [&::-webkit-details-marker]:hidden">
        {title}
      </summary>
      <div className="space-y-4 border-t border-border px-3 py-3">
        <OverrideToggle
          label="Override match count"
          checked={matchExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(draft, "match_count", matchValue)
                : clearRetrievalOverride(draft, "match_count"),
            );
          }}
        >
          <input
            type="number"
            min={MIN_MATCH_COUNT}
            max={MAX_MATCH_COUNT}
            value={matchValue}
            disabled={disabled}
            onChange={(e) =>
              onChange(
                setRetrievalOverride(
                  draft,
                  "match_count",
                  Number(e.target.value),
                ),
              )
            }
            className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-foreground outline-none focus:border-accent"
          />
        </OverrideToggle>

        <OverrideToggle
          label="Override hybrid retrieval"
          checked={hybridExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(draft, "hybrid_enabled", hybridValue)
                : clearRetrievalOverride(draft, "hybrid_enabled"),
            );
          }}
        >
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={hybridValue}
              disabled={disabled}
              onChange={(e) =>
                onChange(
                  setRetrievalOverride(
                    draft,
                    "hybrid_enabled",
                    e.target.checked,
                  ),
                )
              }
              className="h-3.5 w-3.5 accent-[color:var(--accent)]"
            />
            <span>Hybrid enabled</span>
          </label>
        </OverrideToggle>

        <OverrideToggle
          label="Override reranking"
          checked={rerankExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(
                    draft,
                    "reranking_enabled",
                    rerankValue,
                  )
                : clearRetrievalOverride(draft, "reranking_enabled"),
            );
          }}
        >
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={rerankValue}
              disabled={disabled}
              onChange={(e) =>
                onChange(
                  setRetrievalOverride(
                    draft,
                    "reranking_enabled",
                    e.target.checked,
                  ),
                )
              }
              className="h-3.5 w-3.5 accent-[color:var(--accent)]"
            />
            <span>Reranking enabled</span>
          </label>
        </OverrideToggle>

        <OverrideToggle
          label="Override reranker provider"
          checked={providerExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(
                    draft,
                    "reranker_provider",
                    providerValue,
                  )
                : clearRetrievalOverride(draft, "reranker_provider"),
            );
          }}
        >
          <select
            value={providerValue}
            disabled={disabled}
            onChange={(e) =>
              onChange(
                setRetrievalOverride(
                  draft,
                  "reranker_provider",
                  e.target.value as RerankerProvider,
                ),
              )
            }
            className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-foreground outline-none focus:border-accent"
          >
            <option value="similarity">similarity</option>
          </select>
        </OverrideToggle>

        <OverrideToggle
          label="Override query transformation"
          checked={transformExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(
                    draft,
                    "query_transformation_enabled",
                    transformValue,
                  )
                : clearRetrievalOverride(
                    draft,
                    "query_transformation_enabled",
                  ),
            );
          }}
        >
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={transformValue}
              disabled={disabled}
              onChange={(e) =>
                onChange(
                  setRetrievalOverride(
                    draft,
                    "query_transformation_enabled",
                    e.target.checked,
                  ),
                )
              }
              className="h-3.5 w-3.5 accent-[color:var(--accent)]"
            />
            <span>Transformation enabled</span>
          </label>
        </OverrideToggle>

        <OverrideToggle
          label="Override transform strategy"
          checked={strategyExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(
                    draft,
                    "query_transformation_strategy",
                    strategyValue,
                  )
                : clearRetrievalOverride(
                    draft,
                    "query_transformation_strategy",
                  ),
            );
          }}
        >
          <select
            value={strategyValue}
            disabled={disabled}
            onChange={(e) =>
              onChange(
                setRetrievalOverride(
                  draft,
                  "query_transformation_strategy",
                  e.target.value as QueryTransformationStrategy,
                ),
              )
            }
            className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-foreground outline-none focus:border-accent"
          >
            {TRANSFORM_STRATEGIES.map((strategy) => (
              <option key={strategy} value={strategy}>
                {strategy}
              </option>
            ))}
          </select>
        </OverrideToggle>

        <OverrideToggle
          label="Override history-aware retrieval"
          checked={historyAwareExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(
                    draft,
                    "history_aware_retrieval",
                    historyAwareValue,
                  )
                : clearRetrievalOverride(draft, "history_aware_retrieval"),
            );
          }}
        >
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={historyAwareValue}
              disabled={disabled}
              onChange={(e) =>
                onChange(
                  setRetrievalOverride(
                    draft,
                    "history_aware_retrieval",
                    e.target.checked,
                  ),
                )
              }
              className="h-3.5 w-3.5 accent-[color:var(--accent)]"
            />
            <span>History-aware retrieval</span>
          </label>
        </OverrideToggle>

        <OverrideToggle
          label="Override retrieval history window"
          checked={retrievalWindowExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(
                    draft,
                    "retrieval_history_window",
                    retrievalWindowValue,
                  )
                : clearRetrievalOverride(draft, "retrieval_history_window"),
            );
          }}
        >
          <input
            type="number"
            min={0}
            max={100}
            value={retrievalWindowValue}
            disabled={disabled}
            onChange={(e) =>
              onChange(
                setRetrievalOverride(
                  draft,
                  "retrieval_history_window",
                  Number(e.target.value),
                ),
              )
            }
            className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-foreground outline-none focus:border-accent"
          />
        </OverrideToggle>

        <OverrideToggle
          label="Override generation history window"
          checked={generationWindowExplicit}
          disabled={disabled}
          onChange={(enabled) => {
            onChange(
              enabled
                ? setRetrievalOverride(
                    draft,
                    "generation_history_window",
                    generationWindowValue,
                  )
                : clearRetrievalOverride(draft, "generation_history_window"),
            );
          }}
        >
          <input
            type="number"
            min={0}
            max={100}
            value={generationWindowValue}
            disabled={disabled}
            onChange={(e) =>
              onChange(
                setRetrievalOverride(
                  draft,
                  "generation_history_window",
                  Number(e.target.value),
                ),
              )
            }
            className="w-full rounded-md border border-border bg-surface px-2 py-1.5 text-foreground outline-none focus:border-accent"
          />
        </OverrideToggle>
      </div>
    </details>
  );
}

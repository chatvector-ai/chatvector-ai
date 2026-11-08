/**
 * Sparse per-request retrieval overrides (same rules as the advanced drawer).
 * Only fields the developer explicitly sets are sent on the wire.
 */

export type RerankerProvider = "similarity" | "cohere";
export type QueryTransformationStrategy =
  | "rewrite"
  | "expand"
  | "stepback"
  | "none";

export type RetrievalOverrideKey =
  | "match_count"
  | "hybrid_enabled"
  | "reranking_enabled"
  | "reranker_provider"
  | "query_transformation_enabled"
  | "query_transformation_strategy"
  | "skip_history_transform"
  | "history_aware_retrieval"
  | "retrieval_history_window"
  | "generation_history_window";

export type RetrievalOverrideValue = number | boolean | string;

export type RetrievalOverrideDraft = {
  explicit: Partial<Record<RetrievalOverrideKey, RetrievalOverrideValue>>;
};

export function createEmptyRetrievalOverrideDraft(): RetrievalOverrideDraft {
  return { explicit: {} };
}

export function isRetrievalOverrideExplicit(
  draft: RetrievalOverrideDraft,
  key: RetrievalOverrideKey,
): boolean {
  return Object.prototype.hasOwnProperty.call(draft.explicit, key);
}

export function setRetrievalOverride(
  draft: RetrievalOverrideDraft,
  key: RetrievalOverrideKey,
  value: RetrievalOverrideValue,
): RetrievalOverrideDraft {
  return {
    explicit: { ...draft.explicit, [key]: value },
  };
}

export function clearRetrievalOverride(
  draft: RetrievalOverrideDraft,
  key: RetrievalOverrideKey,
): RetrievalOverrideDraft {
  const next = { ...draft.explicit };
  delete next[key];
  return { explicit: next };
}

const HISTORY_OVERRIDE_KEYS = new Set<RetrievalOverrideKey>([
  "history_aware_retrieval",
  "retrieval_history_window",
  "generation_history_window",
]);

/** Build top-level batch item fields from explicitly set overrides only. */
export function buildBatchQueryItemFields(
  draft: RetrievalOverrideDraft,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const history: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(draft.explicit) as [
    RetrievalOverrideKey,
    RetrievalOverrideValue,
  ][]) {
    if (HISTORY_OVERRIDE_KEYS.has(key)) {
      history[key] = value;
    } else {
      out[key] = value;
    }
  }

  if (Object.keys(history).length > 0) {
    out.history = history;
  }

  return out;
}

export function buildConfigurationCompareQueryItem(
  question: string,
  docIds: string[],
  draft: RetrievalOverrideDraft,
): Record<string, unknown> {
  return {
    question,
    doc_ids: docIds,
    ...buildBatchQueryItemFields(draft),
  };
}

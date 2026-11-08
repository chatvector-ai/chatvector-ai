import {
  clampMatchCount,
  DEFAULT_MATCH_COUNT,
  type RetrievalScope,
} from "./retrievalSettings";
import type { DocumentScalarMetadata } from "./documentMetadata";
import { parseStoredMetadataFilter } from "./metadataCorpus";

export type QueryTransformationStrategy = "rewrite" | "expand" | "stepback";
export type RerankerProvider = "similarity" | "cohere";

export type AdvancedRetrievalExplicitFields = {
  /** Named preset when the preset picker sets one without an explicit scope override. */
  preset?: string;
  scope?: RetrievalScope;
  matchCount?: number;
  hybridEnabled?: boolean;
  rerankingEnabled?: boolean;
  rerankerProvider?: RerankerProvider;
  queryTransformationEnabled?: boolean;
  queryTransformationStrategy?: QueryTransformationStrategy;
  historyAwareRetrieval?: boolean;
  retrievalHistoryWindow?: number;
  generationHistoryWindow?: number;
  metadataFilter?: DocumentScalarMetadata;
};

export type AdvancedRetrievalState = {
  explicit: AdvancedRetrievalExplicitFields;
};

export const EMPTY_ADVANCED_RETRIEVAL: AdvancedRetrievalState = {
  explicit: {},
};

const STORAGE_KEY = "chatvector-advanced-retrieval-explicit";
const LEGACY_STORAGE_KEY = "chatvector-retrieval-settings";

export const DEFAULT_DISPLAY_SCOPE: RetrievalScope = "session";
export const DEFAULT_DISPLAY_MATCH_COUNT = DEFAULT_MATCH_COUNT;

export function effectiveScope(state: AdvancedRetrievalState): RetrievalScope {
  return state.explicit.scope ?? DEFAULT_DISPLAY_SCOPE;
}

export function effectiveMatchCount(state: AdvancedRetrievalState): number {
  return clampMatchCount(
    state.explicit.matchCount ?? DEFAULT_DISPLAY_MATCH_COUNT
  );
}

export function selectedPresetName(
  state: AdvancedRetrievalState
): string | undefined {
  const name = state.explicit.preset;
  if (typeof name !== "string") return undefined;
  const trimmed = name.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

export type ScopeIndicatorKind =
  | { kind: "session"; fileName?: string }
  | { kind: "tenant" }
  | { kind: "preset" }
  | { kind: "default-session"; fileName?: string };

/** Simple composer scope line — omits session/tenant when only a preset applies. */
export function resolveScopeIndicator(
  state: AdvancedRetrievalState,
  attachmentFileName?: string | null
): ScopeIndicatorKind {
  if (state.explicit.scope === "tenant") {
    return { kind: "tenant" };
  }
  if (state.explicit.scope === "session") {
    return { kind: "session", fileName: attachmentFileName ?? undefined };
  }
  if (selectedPresetName(state)) {
    return { kind: "preset" };
  }
  return {
    kind: "default-session",
    fileName: attachmentFileName ?? undefined,
  };
}

export type FieldInheritSource = "explicit" | "preset" | "process-default";

export function fieldInheritSource(
  state: AdvancedRetrievalState,
  fieldSet: boolean
): FieldInheritSource {
  if (fieldSet) return "explicit";
  if (selectedPresetName(state)) return "preset";
  return "process-default";
}

export function inheritSourceLabel(source: FieldInheritSource): string {
  switch (source) {
    case "explicit":
      return "Explicit override";
    case "preset":
      return "Follows selected preset";
    default:
      return "Process default";
  }
}

function isRetrievalScope(value: unknown): value is RetrievalScope {
  return value === "session" || value === "tenant";
}

function isStrategy(value: unknown): value is QueryTransformationStrategy {
  return value === "rewrite" || value === "expand" || value === "stepback";
}

function isRerankerProvider(value: unknown): value is RerankerProvider {
  return value === "similarity" || value === "cohere";
}

function parseExplicitFields(
  raw: unknown
): AdvancedRetrievalExplicitFields {
  if (raw == null || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }
  const obj = raw as Record<string, unknown>;
  const explicit: AdvancedRetrievalExplicitFields = {};
  if (typeof obj.preset === "string") {
    const trimmed = obj.preset.trim();
    if (trimmed.length > 0) explicit.preset = trimmed;
  }
  if (isRetrievalScope(obj.scope)) explicit.scope = obj.scope;
  if (typeof obj.matchCount === "number") {
    explicit.matchCount = clampMatchCount(obj.matchCount);
  }
  if (typeof obj.hybridEnabled === "boolean") {
    explicit.hybridEnabled = obj.hybridEnabled;
  }
  if (typeof obj.rerankingEnabled === "boolean") {
    explicit.rerankingEnabled = obj.rerankingEnabled;
  }
  if (isRerankerProvider(obj.rerankerProvider)) {
    explicit.rerankerProvider = obj.rerankerProvider;
  }
  if (typeof obj.queryTransformationEnabled === "boolean") {
    explicit.queryTransformationEnabled = obj.queryTransformationEnabled;
  }
  if (isStrategy(obj.queryTransformationStrategy)) {
    explicit.queryTransformationStrategy = obj.queryTransformationStrategy;
  }
  if (typeof obj.historyAwareRetrieval === "boolean") {
    explicit.historyAwareRetrieval = obj.historyAwareRetrieval;
  }
  if (typeof obj.retrievalHistoryWindow === "number") {
    explicit.retrievalHistoryWindow = Math.round(obj.retrievalHistoryWindow);
  }
  if (typeof obj.generationHistoryWindow === "number") {
    explicit.generationHistoryWindow = Math.round(obj.generationHistoryWindow);
  }
  const metadataFilter = parseStoredMetadataFilter(obj.metadataFilter);
  if (metadataFilter !== undefined) {
    explicit.metadataFilter = metadataFilter;
  }
  return explicit;
}

export function hasActiveMetadataFilter(
  state: AdvancedRetrievalState
): boolean {
  const filter = state.explicit.metadataFilter;
  return filter !== undefined && Object.keys(filter).length > 0;
}

export function loadAdvancedRetrievalState(): AdvancedRetrievalState {
  if (typeof sessionStorage === "undefined") {
    return EMPTY_ADVANCED_RETRIEVAL;
  }
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { explicit?: unknown };
      return { explicit: parseExplicitFields(parsed.explicit) };
    }
    const legacy = sessionStorage.getItem(LEGACY_STORAGE_KEY);
    if (legacy) {
      sessionStorage.removeItem(LEGACY_STORAGE_KEY);
    }
  } catch {
    /* ignore */
  }
  return EMPTY_ADVANCED_RETRIEVAL;
}

export function saveAdvancedRetrievalState(state: AdvancedRetrievalState): void {
  if (typeof sessionStorage === "undefined") return;
  if (Object.keys(state.explicit).length === 0) {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    return;
  }
  try {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ explicit: state.explicit })
    );
  } catch {
    /* ignore */
  }
}

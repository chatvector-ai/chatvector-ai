export type RetrievalScope = "session" | "tenant";

export type RetrievalSettings = {
  scope: RetrievalScope;
  matchCount: number;
};

export const MIN_MATCH_COUNT = 1;
export const MAX_MATCH_COUNT = 20;
export const DEFAULT_MATCH_COUNT = 5;

export const DEFAULT_RETRIEVAL_SETTINGS: RetrievalSettings = {
  scope: "session",
  matchCount: DEFAULT_MATCH_COUNT,
};

const STORAGE_KEY = "chatvector-retrieval-settings";

export function clampMatchCount(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_MATCH_COUNT;
  return Math.min(
    MAX_MATCH_COUNT,
    Math.max(MIN_MATCH_COUNT, Math.round(value))
  );
}

function isRetrievalScope(value: unknown): value is RetrievalScope {
  return value === "session" || value === "tenant";
}

export function loadRetrievalSettings(): RetrievalSettings {
  if (typeof sessionStorage === "undefined") {
    return DEFAULT_RETRIEVAL_SETTINGS;
  }
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_RETRIEVAL_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<RetrievalSettings>;
    return {
      scope: isRetrievalScope(parsed.scope)
        ? parsed.scope
        : DEFAULT_RETRIEVAL_SETTINGS.scope,
      matchCount: clampMatchCount(
        parsed.matchCount ?? DEFAULT_RETRIEVAL_SETTINGS.matchCount
      ),
    };
  } catch {
    return DEFAULT_RETRIEVAL_SETTINGS;
  }
}

export function saveRetrievalSettings(settings: RetrievalSettings): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

/** Matches backend `CHAT_BATCH_MAX_ITEMS` default in `core/config.py`. */
export const BATCH_MAX_COMPARE_ITEMS = 20;

/** Matches backend `CHAT_MAX_DOC_IDS_PER_QUERY` default in `core/config.py`. */
export const BATCH_MAX_SYNTHESIZE_DOC_IDS = 10;

export type BatchSelectionMode = "compare" | "synthesize" | "config-compare";

export function batchSelectionLimit(mode: BatchSelectionMode): number {
  if (mode === "compare") {
    return BATCH_MAX_COMPARE_ITEMS;
  }
  return BATCH_MAX_SYNTHESIZE_DOC_IDS;
}

export function canAddBatchSelection(
  mode: BatchSelectionMode,
  selectedCount: number,
): boolean {
  return selectedCount < batchSelectionLimit(mode);
}

export function batchSelectionWithinLimit(
  mode: BatchSelectionMode,
  selectedCount: number,
): boolean {
  return selectedCount > 0 && selectedCount <= batchSelectionLimit(mode);
}

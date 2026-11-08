"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Settings2, X } from "lucide-react";
import {
  effectiveMatchCount,
  fieldInheritSource,
  inheritSourceLabel,
  selectedPresetName,
  type AdvancedRetrievalState,
  type QueryTransformationStrategy,
  type RerankerProvider,
} from "../lib/advancedRetrieval";
import {
  MAX_MATCH_COUNT,
  MIN_MATCH_COUNT,
  type RetrievalScope,
} from "../lib/retrievalSettings";
import { formatMetadataPair } from "../lib/documentMetadata";
import {
  collectMetadataKeys,
  distinctMetadataValuesForKey,
  type MetadataCorpusDocument,
} from "../lib/metadataCorpus";
import type { DocumentScalarMetadata } from "../lib/documentMetadata";
import { InfoPopover } from "./ui/InfoPopover";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  state: AdvancedRetrievalState;
  onScopeChange: (scope: RetrievalScope) => void;
  onMatchCountChange: (matchCount: number) => void;
  onHybridEnabledChange: (enabled: boolean) => void;
  onRerankingEnabledChange: (enabled: boolean) => void;
  onRerankerProviderChange: (provider: RerankerProvider) => void;
  onQueryTransformationEnabledChange: (enabled: boolean) => void;
  onQueryTransformationStrategyChange: (strategy: QueryTransformationStrategy) => void;
  onHistoryAwareRetrievalChange: (enabled: boolean) => void;
  onRetrievalHistoryWindowChange: (value: number) => void;
  onGenerationHistoryWindowChange: (value: number) => void;
  onMetadataFilterChange: (filter: DocumentScalarMetadata | undefined) => void;
  onPresetChange: (preset: string | undefined) => void;
  metadataCorpus: MetadataCorpusDocument[];
  availablePresets: string[];
  availableRerankerProviders: RerankerProvider[];
  inspectMode?: boolean;
  onInspectModeChange?: (enabled: boolean) => void;
};

const TRANSFORM_STRATEGIES: { value: QueryTransformationStrategy; label: string }[] = [
  { value: "rewrite", label: "Rewrite" },
  { value: "expand", label: "Expand" },
  { value: "stepback", label: "Step back" },
];

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.offsetParent !== null || el.getClientRects().length > 0
  );
}

export default function AdvancedRetrievalDrawer({
  open,
  onOpenChange,
  state,
  onScopeChange,
  onMatchCountChange,
  onHybridEnabledChange,
  onRerankingEnabledChange,
  onRerankerProviderChange,
  onQueryTransformationEnabledChange,
  onQueryTransformationStrategyChange,
  onHistoryAwareRetrievalChange,
  onRetrievalHistoryWindowChange,
  onGenerationHistoryWindowChange,
  onMetadataFilterChange,
  onPresetChange,
  metadataCorpus,
  availablePresets,
  availableRerankerProviders,
  inspectMode = false,
  onInspectModeChange,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const [matchCountEditorOpen, setMatchCountEditorOpen] = useState(false);
  const [retrievalWindowEditorOpen, setRetrievalWindowEditorOpen] =
    useState(false);
  const [generationWindowEditorOpen, setGenerationWindowEditorOpen] =
    useState(false);
  const [matchCountDraft, setMatchCountDraft] = useState<number | null>(null);
  const [retrievalWindowDraft, setRetrievalWindowDraft] = useState<
    number | null
  >(null);
  const [generationWindowDraft, setGenerationWindowDraft] = useState<
    number | null
  >(null);
  const activePreset = selectedPresetName(state);
  const scopeInherit = fieldInheritSource(
    state,
    state.explicit.scope !== undefined
  );
  const matchCountInherit = fieldInheritSource(
    state,
    state.explicit.matchCount !== undefined
  );
  const hybridInherit = fieldInheritSource(
    state,
    state.explicit.hybridEnabled !== undefined
  );
  const rerankingInherit = fieldInheritSource(
    state,
    state.explicit.rerankingEnabled !== undefined
  );
  const queryTransformationInherit = fieldInheritSource(
    state,
    state.explicit.queryTransformationEnabled !== undefined
  );
  const historyAwareInherit = fieldInheritSource(
    state,
    state.explicit.historyAwareRetrieval !== undefined
  );
  const matchCountExplicit = state.explicit.matchCount;
  const matchCountEditorVisible =
    matchCountExplicit !== undefined || matchCountEditorOpen;
  const committedMatchCount =
    matchCountExplicit !== undefined ? effectiveMatchCount(state) : null;
  const metadataKeys = useMemo(
    () => collectMetadataKeys(metadataCorpus),
    [metadataCorpus]
  );
  const activeFilter = state.explicit.metadataFilter;
  const selectedFilterKey =
    activeFilter && Object.keys(activeFilter).length === 1
      ? Object.keys(activeFilter)[0]
      : "";
  const selectedFilterValue =
    selectedFilterKey && activeFilter
      ? activeFilter[selectedFilterKey]
      : undefined;
  const valueOptions =
    selectedFilterKey.length > 0
      ? distinctMetadataValuesForKey(metadataCorpus, selectedFilterKey)
      : [];

  useEffect(() => {
    if (!open) return;
    const focusable = getFocusableElements(panelRef.current);
    (focusable[0] ?? panelRef.current)?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
        openerRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  return (
    <>
      <button
        ref={openerRef}
        type="button"
        data-testid="advanced-retrieval-open"
        onClick={() => onOpenChange(true)}
        className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium text-muted transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <Settings2 size={14} aria-hidden />
        Advanced retrieval
      </button>

      {open && (
        <>
          <div
            data-testid="advanced-retrieval-backdrop"
            className="absolute inset-0 z-30 bg-black/40"
            onClick={() => onOpenChange(false)}
            aria-hidden="true"
          />
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label="Advanced retrieval settings"
            data-testid="advanced-retrieval-drawer"
            tabIndex={-1}
            className="absolute inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border bg-surface shadow-xl"
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold text-foreground">
                Advanced retrieval
              </h2>
              <button
                type="button"
                aria-label="Close advanced retrieval"
                onClick={() => {
                  onOpenChange(false);
                  openerRef.current?.focus();
                }}
                className="rounded-md p-1 text-muted transition-colors hover:bg-background hover:text-foreground"
              >
                <X size={18} aria-hidden />
              </button>
            </div>

            <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4 text-xs">
              <section>
                <div className="mb-2 flex items-center gap-1.5">
                  <p className="font-medium text-foreground">Preset</p>
                  <InfoPopover label="Preset help">
                    Names loaded at API startup. A preset fills omitted retrieval
                    fields; explicit drawer values still override the preset on
                    the request.
                  </InfoPopover>
                </div>
                <label className="block">
                  <span className="sr-only">Retrieval preset</span>
                  <select
                    data-testid="retrieval-preset-picker"
                    value={state.explicit.preset ?? ""}
                    onChange={(e) =>
                      onPresetChange(e.target.value || undefined)
                    }
                    className="w-full max-w-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground outline-none focus:border-accent"
                  >
                    <option value="">None</option>
                    {availablePresets.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                {availablePresets.length === 0 && (
                  <p className="mt-2 text-muted">No presets are loaded.</p>
                )}
              </section>

              <section>
                <div className="mb-2 flex items-center gap-1.5">
                  <p className="font-medium text-foreground">Metadata filter</p>
                  <InfoPopover label="Metadata filter help">
                    Exact match on document metadata keys present in your
                    current documents. Omitting a filter leaves retrieval
                    unchanged.
                  </InfoPopover>
                </div>
                {metadataKeys.length === 0 ? (
                  <p className="text-muted">
                    No metadata on the current documents.
                  </p>
                ) : (
                  <div className="space-y-2">
                    <label className="block">
                      <span className="mb-1 block text-muted">Key</span>
                      <select
                        data-testid="metadata-filter-key"
                        value={selectedFilterKey}
                        onChange={(e) => {
                          const key = e.target.value;
                          if (!key) {
                            onMetadataFilterChange(undefined);
                            return;
                          }
                          const values = distinctMetadataValuesForKey(
                            metadataCorpus,
                            key
                          );
                          const first = values[0];
                          if (first === undefined) {
                            onMetadataFilterChange(undefined);
                            return;
                          }
                          onMetadataFilterChange({ [key]: first });
                        }}
                        className="w-full max-w-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground outline-none focus:border-accent"
                      >
                        <option value="">None</option>
                        {metadataKeys.map((key) => (
                          <option key={key} value={key}>
                            {key}
                          </option>
                        ))}
                      </select>
                    </label>
                    {selectedFilterKey && (
                      <label className="block">
                        <span className="mb-1 block text-muted">Value</span>
                        <select
                          data-testid="metadata-filter-value"
                          value={
                            selectedFilterValue !== undefined
                              ? String(selectedFilterValue)
                              : ""
                          }
                          onChange={(e) => {
                            const picked = valueOptions.find(
                              (v) => String(v) === e.target.value
                            );
                            if (picked === undefined) return;
                            onMetadataFilterChange({
                              [selectedFilterKey]: picked,
                            });
                          }}
                          className="w-full max-w-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground outline-none focus:border-accent"
                        >
                          {valueOptions.map((value) => (
                            <option key={String(value)} value={String(value)}>
                              {formatMetadataPair(selectedFilterKey, value)}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {activeFilter && Object.keys(activeFilter).length > 0 && (
                      <button
                        type="button"
                        data-testid="metadata-filter-clear"
                        onClick={() => onMetadataFilterChange(undefined)}
                        className="text-accent hover:underline"
                      >
                        Clear metadata filter
                      </button>
                    )}
                  </div>
                )}
              </section>

              <section>
                <div className="mb-2 flex items-center gap-1.5">
                  <p className="font-medium text-foreground">Scope</p>
                  <InfoPopover label="Scope help">
                    <p>
                      <strong className="font-medium text-foreground/80">Session</strong>{" "}
                      searches only the selected document attached to this chat.
                    </p>
                    <p className="mt-3">
                      <strong className="font-medium text-foreground/80">Tenant</strong>{" "}
                      searches the tenant&apos;s ready documents.
                    </p>
                  </InfoPopover>
                </div>
                <p className="mb-2 text-muted" data-testid="scope-inherit-label">
                  {inheritSourceLabel(scopeInherit)}
                  {scopeInherit === "process-default" ? " (session)" : null}
                  {scopeInherit === "preset" && activePreset
                    ? ` (${activePreset})`
                    : null}
                </p>
                <div
                  className="inline-flex rounded-lg border border-border bg-background p-0.5"
                  role="radiogroup"
                  aria-label="Retrieval scope"
                >
                  {(["session", "tenant"] as const).map((scope) => (
                    <label key={scope} className="cursor-pointer">
                      <input
                        type="radio"
                        name="advanced-retrieval-scope"
                        value={scope}
                        checked={state.explicit.scope === scope}
                        onChange={() => onScopeChange(scope)}
                        className="sr-only"
                      />
                      <span
                        className={`inline-block rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                          state.explicit.scope === scope
                            ? "bg-accent text-accent-foreground"
                            : "text-muted hover:text-foreground"
                        }`}
                      >
                        {scope}
                      </span>
                    </label>
                  ))}
                </div>
              </section>

              <section>
                <div className="mb-2 flex items-center gap-1.5">
                  <label
                    htmlFor="advanced-match-count"
                    className="font-medium text-foreground"
                  >
                    Match count
                  </label>
                  <InfoPopover label="Match count help">
                    Number of chunks to retrieve per query ({MIN_MATCH_COUNT}–
                    {MAX_MATCH_COUNT}).
                  </InfoPopover>
                </div>
                <p className="mb-2 text-muted" data-testid="match-count-inherit-label">
                  {inheritSourceLabel(matchCountInherit)}
                </p>
                {matchCountEditorVisible ? (
                  <div className="flex items-center gap-3">
                    <input
                      id="advanced-match-count"
                      type="range"
                      min={MIN_MATCH_COUNT}
                      max={MAX_MATCH_COUNT}
                      step={1}
                      value={
                        committedMatchCount ??
                        matchCountDraft ??
                        MIN_MATCH_COUNT
                      }
                      onChange={(e) => {
                        const next = Number(e.target.value);
                        setMatchCountDraft(next);
                        onMatchCountChange(next);
                      }}
                      aria-valuemin={MIN_MATCH_COUNT}
                      aria-valuemax={MAX_MATCH_COUNT}
                      aria-valuenow={
                        committedMatchCount ?? matchCountDraft ?? undefined
                      }
                      className="h-1.5 flex-1 accent-[color:var(--accent)]"
                    />
                    <input
                      type="number"
                      min={MIN_MATCH_COUNT}
                      max={MAX_MATCH_COUNT}
                      step={1}
                      value={committedMatchCount ?? matchCountDraft ?? ""}
                      placeholder="—"
                      onChange={(e) => {
                        const next = Number(e.target.value);
                        if (Number.isNaN(next)) return;
                        setMatchCountDraft(next);
                        onMatchCountChange(next);
                      }}
                      aria-label="Match count"
                      className="w-14 rounded-md border border-border bg-background px-2 py-1 text-center text-xs text-foreground outline-none focus:border-accent"
                    />
                  </div>
                ) : (
                  <button
                    type="button"
                    data-testid="match-count-set-explicit"
                    onClick={() => {
                      setMatchCountDraft(null);
                      setMatchCountEditorOpen(true);
                    }}
                    className="text-accent hover:underline"
                  >
                    Set match count explicitly
                  </button>
                )}
              </section>

              <section className="space-y-3">
                <div>
                  <p
                    className="mb-1 text-muted"
                    data-testid="hybrid-inherit-label"
                  >
                    {inheritSourceLabel(hybridInherit)}
                  </p>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={state.explicit.hybridEnabled === true}
                      onChange={(e) => onHybridEnabledChange(e.target.checked)}
                      className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                    />
                    <span className="font-medium text-foreground">Hybrid search</span>
                  </label>
                </div>
                <div>
                  <p
                    className="mb-1 text-muted"
                    data-testid="reranking-inherit-label"
                  >
                    {inheritSourceLabel(rerankingInherit)}
                  </p>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={state.explicit.rerankingEnabled === true}
                      onChange={(e) => onRerankingEnabledChange(e.target.checked)}
                      className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                    />
                    <span className="font-medium text-foreground">Reranking</span>
                  </label>
                </div>
                <div>
                  <p className="mb-2 font-medium text-foreground">Reranker provider</p>
                  {state.explicit.rerankerProvider === undefined ? (
                    <p className="mb-2 text-muted">
                      {inheritSourceLabel(
                        fieldInheritSource(
                          state,
                          state.explicit.rerankerProvider !== undefined
                        )
                      )}
                    </p>
                  ) : null}
                  <div
                    className="inline-flex flex-wrap gap-1 rounded-lg border border-border bg-background p-0.5"
                    role="radiogroup"
                    aria-label="Reranker provider"
                  >
                    {availableRerankerProviders.map((provider) => (
                      <label key={provider} className="cursor-pointer">
                        <input
                          type="radio"
                          name="advanced-reranker-provider"
                          value={provider}
                          checked={state.explicit.rerankerProvider === provider}
                          onChange={() => onRerankerProviderChange(provider)}
                          className="sr-only"
                        />
                        <span
                          className={`inline-block rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                            state.explicit.rerankerProvider === provider
                              ? "bg-accent text-accent-foreground"
                              : "text-muted hover:text-foreground"
                          }`}
                        >
                          {provider}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              </section>

              <section className="space-y-3">
                <div>
                  <p
                    className="mb-1 text-muted"
                    data-testid="query-transformation-inherit-label"
                  >
                    {inheritSourceLabel(queryTransformationInherit)}
                  </p>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={state.explicit.queryTransformationEnabled === true}
                      onChange={(e) =>
                        onQueryTransformationEnabledChange(e.target.checked)
                      }
                      className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                    />
                    <span className="font-medium text-foreground">
                      Query transformation
                    </span>
                  </label>
                </div>
                <label className="block">
                  <span className="mb-1 block font-medium text-foreground">
                    Transform strategy
                  </span>
                  {state.explicit.queryTransformationStrategy === undefined ? (
                    <p className="mb-1 text-muted">
                      {inheritSourceLabel(
                        fieldInheritSource(
                          state,
                          state.explicit.queryTransformationStrategy !== undefined
                        )
                      )}
                    </p>
                  ) : null}
                  <select
                    value={state.explicit.queryTransformationStrategy ?? ""}
                    onChange={(e) => {
                      const value = e.target.value;
                      if (!value) return;
                      onQueryTransformationStrategyChange(
                        value as QueryTransformationStrategy
                      );
                    }}
                    className="w-full max-w-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground outline-none focus:border-accent"
                  >
                    <option value="">Set strategy…</option>
                    {TRANSFORM_STRATEGIES.map(({ value: v, label }) => (
                      <option key={v} value={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              </section>

              <section className="space-y-3">
                <div>
                  <p
                    className="mb-1 text-muted"
                    data-testid="history-aware-inherit-label"
                  >
                    {inheritSourceLabel(historyAwareInherit)}
                  </p>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={state.explicit.historyAwareRetrieval === true}
                      onChange={(e) =>
                        onHistoryAwareRetrievalChange(e.target.checked)
                      }
                      className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                    />
                    <span className="font-medium text-foreground">
                      History-aware retrieval
                    </span>
                  </label>
                </div>
                <div>
                  <span className="mb-1 block font-medium text-foreground">
                    Retrieval history window
                  </span>
                  {state.explicit.retrievalHistoryWindow === undefined &&
                  !retrievalWindowEditorOpen ? (
                    <>
                      <p className="mb-1 text-muted">
                        {inheritSourceLabel(
                          fieldInheritSource(
                            state,
                            state.explicit.retrievalHistoryWindow !== undefined
                          )
                        )}
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setRetrievalWindowDraft(null);
                          setRetrievalWindowEditorOpen(true);
                        }}
                        className="text-accent hover:underline"
                      >
                        Set retrieval history window
                      </button>
                    </>
                  ) : (
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={
                        state.explicit.retrievalHistoryWindow ??
                        retrievalWindowDraft ??
                        ""
                      }
                      placeholder="—"
                      onChange={(e) => {
                        const next = Number(e.target.value);
                        if (Number.isNaN(next)) return;
                        setRetrievalWindowDraft(next);
                        onRetrievalHistoryWindowChange(next);
                      }}
                      className="w-24 rounded-md border border-border bg-background px-2 py-1 text-foreground outline-none focus:border-accent"
                    />
                  )}
                </div>
                <div>
                  <span className="mb-1 block font-medium text-foreground">
                    Generation history window
                  </span>
                  {state.explicit.generationHistoryWindow === undefined &&
                  !generationWindowEditorOpen ? (
                    <>
                      <p className="mb-1 text-muted">
                        {inheritSourceLabel(
                          fieldInheritSource(
                            state,
                            state.explicit.generationHistoryWindow !== undefined
                          )
                        )}
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setGenerationWindowDraft(null);
                          setGenerationWindowEditorOpen(true);
                        }}
                        className="text-accent hover:underline"
                      >
                        Set generation history window
                      </button>
                    </>
                  ) : (
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={
                        state.explicit.generationHistoryWindow ??
                        generationWindowDraft ??
                        ""
                      }
                      placeholder="—"
                      onChange={(e) => {
                        const next = Number(e.target.value);
                        if (Number.isNaN(next)) return;
                        setGenerationWindowDraft(next);
                        onGenerationHistoryWindowChange(next);
                      }}
                      className="w-24 rounded-md border border-border bg-background px-2 py-1 text-foreground outline-none focus:border-accent"
                    />
                  )}
                </div>
              </section>

              {onInspectModeChange && (
                <section>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={inspectMode}
                      onChange={(e) => onInspectModeChange(e.target.checked)}
                      className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                    />
                    <span className="text-foreground">
                      Request retrieval debug payload
                    </span>
                  </label>
                </section>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}

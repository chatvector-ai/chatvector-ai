"use client";

import { useEffect, useRef } from "react";
import { Settings2, X } from "lucide-react";
import {
  effectiveMatchCount,
  effectiveScope,
  type AdvancedRetrievalState,
  type QueryTransformationStrategy,
  type RerankerProvider,
} from "../lib/advancedRetrieval";
import {
  MAX_MATCH_COUNT,
  MIN_MATCH_COUNT,
  type RetrievalScope,
} from "../lib/retrievalSettings";
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
  availableRerankerProviders,
  inspectMode = false,
  onInspectModeChange,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const displayScope = effectiveScope(state);
  const displayMatchCount = effectiveMatchCount(state);
  const displayHybrid = state.explicit.hybridEnabled ?? false;
  const displayReranking = state.explicit.rerankingEnabled ?? false;
  const displayReranker = state.explicit.rerankerProvider ?? "similarity";
  const displayTransformEnabled =
    state.explicit.queryTransformationEnabled ?? false;
  const displayTransformStrategy =
    state.explicit.queryTransformationStrategy ?? "rewrite";
  const displayHistoryAware = state.explicit.historyAwareRetrieval ?? true;
  const displayRetrievalWindow = state.explicit.retrievalHistoryWindow ?? 4;
  const displayGenerationWindow = state.explicit.generationHistoryWindow ?? 8;

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
                        checked={displayScope === scope}
                        onChange={() => onScopeChange(scope)}
                        className="sr-only"
                      />
                      <span
                        className={`inline-block rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                          displayScope === scope
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
                <div className="flex items-center gap-3">
                  <input
                    id="advanced-match-count"
                    type="range"
                    min={MIN_MATCH_COUNT}
                    max={MAX_MATCH_COUNT}
                    step={1}
                    value={displayMatchCount}
                    onChange={(e) => onMatchCountChange(Number(e.target.value))}
                    aria-valuemin={MIN_MATCH_COUNT}
                    aria-valuemax={MAX_MATCH_COUNT}
                    aria-valuenow={displayMatchCount}
                    className="h-1.5 flex-1 accent-[color:var(--accent)]"
                  />
                  <input
                    type="number"
                    min={MIN_MATCH_COUNT}
                    max={MAX_MATCH_COUNT}
                    step={1}
                    value={displayMatchCount}
                    onChange={(e) => onMatchCountChange(Number(e.target.value))}
                    aria-label="Match count"
                    className="w-14 rounded-md border border-border bg-background px-2 py-1 text-center text-xs text-foreground outline-none focus:border-accent"
                  />
                </div>
              </section>

              <section className="space-y-3">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={displayHybrid}
                    onChange={(e) => onHybridEnabledChange(e.target.checked)}
                    className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                  />
                  <span className="font-medium text-foreground">Hybrid search</span>
                </label>
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={displayReranking}
                    onChange={(e) => onRerankingEnabledChange(e.target.checked)}
                    className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                  />
                  <span className="font-medium text-foreground">Reranking</span>
                </label>
                <div>
                  <p className="mb-2 font-medium text-foreground">Reranker provider</p>
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
                          checked={displayReranker === provider}
                          onChange={() => onRerankerProviderChange(provider)}
                          className="sr-only"
                        />
                        <span
                          className={`inline-block rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                            displayReranker === provider
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
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={displayTransformEnabled}
                    onChange={(e) =>
                      onQueryTransformationEnabledChange(e.target.checked)
                    }
                    className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                  />
                  <span className="font-medium text-foreground">
                    Query transformation
                  </span>
                </label>
                <label className="block">
                  <span className="mb-1 block font-medium text-foreground">
                    Transform strategy
                  </span>
                  <select
                    value={displayTransformStrategy}
                    onChange={(e) =>
                      onQueryTransformationStrategyChange(
                        e.target.value as QueryTransformationStrategy
                      )
                    }
                    className="w-full max-w-xs rounded-md border border-border bg-background px-2 py-1.5 text-foreground outline-none focus:border-accent"
                  >
                    {TRANSFORM_STRATEGIES.map(({ value: v, label }) => (
                      <option key={v} value={v}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
              </section>

              <section className="space-y-3">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={displayHistoryAware}
                    onChange={(e) =>
                      onHistoryAwareRetrievalChange(e.target.checked)
                    }
                    className="h-3.5 w-3.5 accent-[color:var(--accent)]"
                  />
                  <span className="font-medium text-foreground">
                    History-aware retrieval
                  </span>
                </label>
                <label className="block">
                  <span className="mb-1 block font-medium text-foreground">
                    Retrieval history window
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={displayRetrievalWindow}
                    onChange={(e) =>
                      onRetrievalHistoryWindowChange(Number(e.target.value))
                    }
                    className="w-24 rounded-md border border-border bg-background px-2 py-1 text-foreground outline-none focus:border-accent"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block font-medium text-foreground">
                    Generation history window
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={displayGenerationWindow}
                    onChange={(e) =>
                      onGenerationHistoryWindowChange(Number(e.target.value))
                    }
                    className="w-24 rounded-md border border-border bg-background px-2 py-1 text-foreground outline-none focus:border-accent"
                  />
                </label>
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

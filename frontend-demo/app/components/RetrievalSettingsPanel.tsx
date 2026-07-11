"use client";

import {
  MAX_MATCH_COUNT,
  MIN_MATCH_COUNT,
  type RetrievalScope,
  type RetrievalSettings,
} from "../lib/retrievalSettings";

type Props = {
  settings: RetrievalSettings;
  onScopeChange: (scope: RetrievalScope) => void;
  onMatchCountChange: (matchCount: number) => void;
};

export default function RetrievalSettingsPanel({
  settings,
  onScopeChange,
  onMatchCountChange,
}: Props) {
  return (
    <details className="rounded-lg border border-border bg-background/40 text-xs">
      <summary className="cursor-pointer list-none px-3 py-2 text-muted transition-colors hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
        <span className="font-medium">Retrieval settings</span>
        <span className="ml-1.5 font-normal text-muted/80">(developer)</span>
      </summary>
      <div className="space-y-4 border-t border-border px-3 py-3">
        <div>
          <p className="mb-2 font-medium text-foreground">Scope</p>
          <div
            className="inline-flex rounded-lg border border-border bg-surface p-0.5"
            role="radiogroup"
            aria-label="Retrieval scope"
          >
            <label className="cursor-pointer">
              <input
                type="radio"
                name="retrieval-scope"
                value="session"
                checked={settings.scope === "session"}
                onChange={() => onScopeChange("session")}
                className="sr-only"
              />
              <span
                className={`inline-block rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  settings.scope === "session"
                    ? "bg-accent text-surface"
                    : "text-muted hover:text-foreground"
                }`}
              >
                Session
              </span>
            </label>
            <label className="cursor-pointer">
              <input
                type="radio"
                name="retrieval-scope"
                value="tenant"
                checked={settings.scope === "tenant"}
                onChange={() => onScopeChange("tenant")}
                className="sr-only"
              />
              <span
                className={`inline-block rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  settings.scope === "tenant"
                    ? "bg-accent text-surface"
                    : "text-muted hover:text-foreground"
                }`}
              >
                Tenant
              </span>
            </label>
          </div>
          <p className="mt-2 text-muted">
            <strong className="font-medium text-foreground/80">Session</strong>{" "}
            limits retrieval to documents attached to this session.{" "}
            <strong className="font-medium text-foreground/80">Tenant</strong>{" "}
            searches all documents registered to the tenant (auth is not
            enforced in demo environments).
          </p>
        </div>

        <div>
          <label
            htmlFor="retrieval-match-count"
            className="mb-2 block font-medium text-foreground"
          >
            Match count
          </label>
          <div className="flex items-center gap-3">
            <input
              id="retrieval-match-count"
              type="range"
              min={MIN_MATCH_COUNT}
              max={MAX_MATCH_COUNT}
              step={1}
              value={settings.matchCount}
              onChange={(e) => onMatchCountChange(Number(e.target.value))}
              className="h-1.5 flex-1 accent-[color:var(--accent)]"
            />
            <input
              type="number"
              min={MIN_MATCH_COUNT}
              max={MAX_MATCH_COUNT}
              step={1}
              value={settings.matchCount}
              onChange={(e) => onMatchCountChange(Number(e.target.value))}
              aria-label="Match count"
              className="w-14 rounded-md border border-border bg-surface px-2 py-1 text-center text-xs text-foreground outline-none focus:border-accent"
            />
          </div>
          <p className="mt-1.5 text-muted">
            Number of chunks to retrieve per query ({MIN_MATCH_COUNT}–
            {MAX_MATCH_COUNT}, default {MIN_MATCH_COUNT + 4}).
          </p>
        </div>
      </div>
    </details>
  );
}

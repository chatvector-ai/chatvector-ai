"use client";

import { FileText, RefreshCw, Trash2 } from "lucide-react";
import DocumentMetadataPairs from "./DocumentMetadataPairs";
import type { DocumentScalarMetadata } from "../lib/documentMetadata";
import type { ActiveScopeMembership } from "../lib/documentListDisplay";

type Props = {
  documentId: string;
  fileName: string;
  fileType: string;
  status: string;
  failureDetail: string | null;
  metadata?: DocumentScalarMetadata;
  inActiveScope?: ActiveScopeMembership;
  isActive?: boolean;
  onMakeActive?: () => void;
  onReplace?: () => void;
  onDelete?: () => void;
  disabled?: boolean;
  leading?: React.ReactNode;
  unavailable?: boolean;
};

export default function DocumentListRow({
  documentId,
  fileName,
  fileType,
  status,
  failureDetail,
  metadata,
  inActiveScope,
  onMakeActive,
  onReplace,
  onDelete,
  disabled = false,
  leading,
  unavailable = false,
}: Props) {
  const isReady = status === "completed" || status === "ready";
  const showActions =
    onMakeActive != null || onReplace != null || onDelete != null;

  return (
    <div
      className="rounded-lg border border-border bg-surface px-3 py-2.5"
      data-testid={`document-list-row-${documentId}`}
    >
      <div className="flex items-start gap-3">
        {leading}
        <FileText size={16} className="mt-0.5 shrink-0 text-muted" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-sm font-medium text-foreground">
              {unavailable ? `Unavailable (${documentId.slice(0, 8)})` : fileName}
            </span>
            {!unavailable && (
              <span className="shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-muted">
                {fileType}
              </span>
            )}
            <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted">
              {unavailable ? "missing" : status}
            </span>
            {inActiveScope === "active-searched" && (
              <span
                className="shrink-0 rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-accent-text"
                data-testid="document-active-searched"
              >
                Active · searched
              </span>
            )}
            {inActiveScope === "not-searched" && (
              <span
                className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted"
                data-testid="document-not-searched"
              >
                Not searched
              </span>
            )}
            {(inActiveScope === true || inActiveScope === "in-scope") && (
              <span
                className="shrink-0 rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-accent-text"
                data-testid="document-in-active-scope"
              >
                In scope
              </span>
            )}
            {inActiveScope === "follows-preset" && (
              <span
                className="shrink-0 rounded-full border border-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted"
                data-testid="document-scope-follows-preset"
              >
                Scope follows preset
              </span>
            )}
          </div>
          {failureDetail && (
            <p
              className="mt-1 text-xs text-red-400"
              data-testid="document-failure-detail"
            >
              {failureDetail}
            </p>
          )}
          {!unavailable && (
            <DocumentMetadataPairs
              metadata={metadata}
              className="mt-1 flex flex-wrap gap-x-2"
            />
          )}
          {unavailable && (
            <p className="mt-1 text-xs text-muted">
              This session document is not on the tenant list.
            </p>
          )}
        </div>
        {showActions && !unavailable && (
          <div className="flex shrink-0 items-center gap-1">
            {onMakeActive && (
              <button
                type="button"
                disabled={disabled || !isReady}
                onClick={onMakeActive}
                className="rounded-md border border-border px-2 py-1 text-xs font-medium text-muted transition hover:bg-background hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                aria-label={`Make ${fileName} active`}
                title="Make active"
              >
                Make active
              </button>
            )}
            {onReplace && (
              <button
                type="button"
                disabled={disabled}
                onClick={onReplace}
                className="rounded-md p-1.5 text-muted transition hover:bg-background hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                aria-label={`Replace ${fileName}`}
                title="Replace file"
              >
                <RefreshCw size={14} />
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                disabled={disabled}
                onClick={onDelete}
                className="rounded-md p-1.5 text-muted transition hover:bg-background hover:text-red-400 disabled:cursor-not-allowed disabled:opacity-50"
                aria-label={`Delete ${fileName}`}
                title="Remove document"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

import { AlertCircle, CheckCircle2 } from "lucide-react";
import {
  softFailureMessage,
  type BatchResultItem,
} from "../../lib/api";
import {
  deduplicatedSources,
  formatCitationLine,
  formatResponseMetadata,
} from "../../lib/citations";
import RetrievalInspector from "../RetrievalInspector";

export function hasPartialBatchResult(result: BatchResultItem): boolean {
  return Boolean(
    result.answer ||
      (result.sources && result.sources.length > 0) ||
      result.chunks !== undefined
  );
}

export function BatchResultCard({
  result,
  title,
}: {
  result: BatchResultItem;
  title: string;
}) {
  const isError = result.status === "error";
  const showPartialContent = isError && hasPartialBatchResult(result);
  const metadata = formatResponseMetadata({
    chunks: result.chunks,
    model: result.model,
    latency_ms: result.latency_ms,
  });

  return (
    <div
      className={`flex flex-col gap-3 rounded-xl border p-4 ${
        isError ? "border-red-500/40 bg-red-500/5" : "border-border bg-surface"
      }`}
    >
      <div className="flex items-center gap-2">
        {isError ? (
          <AlertCircle size={16} className="shrink-0 text-red-500" />
        ) : (
          <CheckCircle2 size={16} className="shrink-0 text-green-500" />
        )}
        <span className="truncate text-sm font-medium" title={title}>
          {title}
        </span>
      </div>

      {isError && (
        <div className="text-sm text-red-500">
          <p>{softFailureMessage(result.error)}</p>
          {result.error?.code && (
            <p className="mt-1 font-mono text-xs text-red-500/80">
              {result.error.code}
            </p>
          )}
        </div>
      )}

      {(!isError || showPartialContent) && result.answer && (
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground">
          {result.answer}
        </p>
      )}

      {!isError && !result.answer && (
        <p className="text-sm text-muted italic">No answer was generated.</p>
      )}

      {result.chunks === 0 && !isError && (
        <p className="text-sm text-muted italic">
          No chunks retrieved for this query.
        </p>
      )}

      {result.sources && result.sources.length > 0 && (
        <div className="mt-auto flex flex-col gap-1 border-t border-border pt-2">
          {deduplicatedSources(result.sources).map((source, sourceIndex) => (
            <span key={sourceIndex} className="text-xs text-muted">
              {formatCitationLine(source)}
            </span>
          ))}
        </div>
      )}

      {metadata && <p className="text-xs text-muted">{metadata}</p>}

      <RetrievalInspector
        data={{
          question: result.question,
          retrieval_debug: result.retrieval_debug,
          sources: result.sources,
          chunks: result.chunks,
          model: result.model,
          latency_ms: result.latency_ms,
        }}
      />
    </div>
  );
}

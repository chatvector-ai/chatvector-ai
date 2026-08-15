import { AlertCircle, CheckCircle2 } from "lucide-react";
import {
  softFailureMessage,
  type BatchResultItem,
} from "../../lib/api";
import AiResponseContent from "../chat/AiResponseContent";
import { InlineAlert } from "../ui/InlineAlert";

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
  const showBody = !isError || showPartialContent;

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
        <div className="flex flex-col gap-1">
          <InlineAlert>{softFailureMessage(result.error)}</InlineAlert>
          {result.error?.code && (
            <p className="ml-6 font-mono text-xs text-red-500/80">
              {result.error.code}
            </p>
          )}
        </div>
      )}

      <AiResponseContent
        text={showBody ? result.answer : undefined}
        sources={result.sources}
        chunks={result.chunks}
        model={result.model}
        latencyMs={result.latency_ms}
        question={result.question}
        retrievalDebug={result.retrieval_debug}
        emptyMessage={
          showBody && !isError && !result.answer
            ? "No answer was generated."
            : undefined
        }
        zeroChunksMessage="No chunks retrieved for this query."
        showZeroChunks={showBody && !isError}
        textClassName="whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground"
        sourceClassName="text-xs text-muted"
        sourcesContainerClassName="mt-auto flex flex-col gap-1 border-t border-border pt-2"
        metadataClassName="text-xs text-muted"
        zeroChunksClassName="text-sm text-muted italic"
      />
    </div>
  );
}

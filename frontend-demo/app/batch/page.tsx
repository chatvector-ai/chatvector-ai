"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Layers, Loader2, FileText, AlertCircle, CheckCircle2 } from "lucide-react";
import {
  sendBatchMessage,
  sendSynthesizedBatchMessage,
  ChatError,
  softFailureMessage,
  type BatchResultItem,
} from "../lib/api";
import {
  deduplicatedSources,
  formatCitationLine,
  formatResponseMetadata,
} from "../lib/citations";
import { getUploadedDocuments, type StoredDocument } from "../lib/documentStore";

type BatchMode = "compare" | "synthesize";

function hasPartialBatchResult(result: BatchResultItem): boolean {
  return Boolean(
    result.answer ||
      (result.sources && result.sources.length > 0) ||
      result.chunks !== undefined
  );
}

function BatchResultCard({
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
    </div>
  );
}

export default function BatchPage() {
  const [documents, setDocuments] = useState<StoredDocument[]>([]);
  const [documentsLoaded, setDocumentsLoaded] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<BatchMode>("compare");
  const [question, setQuestion] = useState("");
  const [inflight, setInflight] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<BatchResultItem[] | null>(null);
  const [summary, setSummary] = useState<{
    count: number;
    success: number;
    failure: number;
  } | null>(null);

  useEffect(() => {
    setDocuments(getUploadedDocuments());
    setDocumentsLoaded(true);
  }, []);

  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const doc of documents) map.set(doc.documentId, doc.fileName);
    return map;
  }, [documents]);

  const selectedDocIds = useMemo(
    () => documents.map((d) => d.documentId).filter((id) => selected.has(id)),
    [documents, selected]
  );

  const synthesizeTitle = useMemo(() => {
    if (selectedDocIds.length === 1) {
      const docId = selectedDocIds[0];
      return nameById.get(docId) ?? docId;
    }
    return `Across ${selectedDocIds.length} documents`;
  }, [selectedDocIds, nameById]);

  const toggle = (documentId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(documentId)) next.delete(documentId);
      else next.add(documentId);
      return next;
    });
  };

  const canSubmit = question.trim().length > 0 && selected.size > 0 && !inflight;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setError(null);
    setResults(null);
    setSummary(null);
    setInflight(true);
    try {
      const response =
        mode === "compare"
          ? await sendBatchMessage(question.trim(), selectedDocIds)
          : await sendSynthesizedBatchMessage(question.trim(), selectedDocIds);
      setResults(response.results);
      setSummary({
        count: response.count,
        success: response.success_count,
        failure: response.failure_count,
      });
    } catch (e) {
      setError(
        e instanceof ChatError ? e.message : "Something went wrong. Please try again."
      );
    } finally {
      setInflight(false);
    }
  };

  return (
    <div
      className="mx-auto w-full max-w-4xl px-4 py-10 text-foreground"
      aria-busy={!documentsLoaded}
    >
      <div className="mb-8">
        <div className="flex items-center gap-2 text-accent">
          <Layers size={20} />
          <span className="text-sm font-medium uppercase tracking-wide">
            Batch Query
          </span>
        </div>
        <h1 className="mt-2 text-3xl font-bold">Ask one question across many documents</h1>
        <p className="mt-2 max-w-2xl text-muted">
          Select documents you&apos;ve uploaded in the chat, enter a single
          question, and choose how ChatVector should answer.
        </p>
      </div>

      {!documentsLoaded ? (
        <div className="flex flex-col gap-6" aria-busy="true">
          <div className="animate-pulse">
            <div className="mb-2 h-4 w-20 rounded bg-border" />
            <div className="h-28 w-full rounded-lg border border-border bg-surface" />
          </div>
          <div className="animate-pulse">
            <div className="mb-2 h-4 w-32 rounded bg-border" />
            <div className="flex flex-col gap-2">
              {Array.from({ length: 3 }).map((_, index) => (
                <div
                  key={index}
                  className="flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3"
                >
                  <div className="h-4 w-4 rounded bg-border" />
                  <div className="h-4 w-4 rounded bg-border" />
                  <div className="h-4 w-40 rounded bg-border" />
                  <div className="ml-auto h-3 w-16 rounded bg-border" />
                </div>
              ))}
            </div>
          </div>
          <div className="h-10 w-40 animate-pulse rounded-lg bg-border" />
        </div>
      ) : documents.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface p-8 text-center">
          <FileText className="mx-auto mb-3 text-muted" size={28} />
          <p className="text-foreground">No documents yet.</p>
          <p className="mt-1 text-sm text-muted">
            Upload a document on the chat page first — it&apos;ll show up here
            automatically.
          </p>
          <Link
            href="/chat"
            className="mt-4 inline-block rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go to chat
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <div>
            <p className="mb-2 text-sm font-medium">Mode</p>
            <div
              className="inline-flex rounded-lg border border-border bg-surface p-1"
              role="radiogroup"
              aria-label="Batch query mode"
            >
              <label className="cursor-pointer">
                <input
                  type="radio"
                  name="batch-mode"
                  value="compare"
                  checked={mode === "compare"}
                  onChange={() => setMode("compare")}
                  className="sr-only"
                />
                <span
                  className={`inline-block rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                    mode === "compare"
                      ? "bg-accent text-surface"
                      : "text-muted hover:text-foreground"
                  }`}
                >
                  Compare
                </span>
              </label>
              <label className="cursor-pointer">
                <input
                  type="radio"
                  name="batch-mode"
                  value="synthesize"
                  checked={mode === "synthesize"}
                  onChange={() => setMode("synthesize")}
                  className="sr-only"
                />
                <span
                  className={`inline-block rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                    mode === "synthesize"
                      ? "bg-accent text-surface"
                      : "text-muted hover:text-foreground"
                  }`}
                >
                  Synthesize
                </span>
              </label>
            </div>
            <p className="mt-2 max-w-2xl text-sm text-muted">
              {mode === "compare" ? (
                <>
                  <strong className="text-foreground">Compare</strong> sends one
                  query per document and shows a separate answer card for each —
                  useful for seeing what each file contributes.
                </>
              ) : (
                <>
                  <strong className="text-foreground">Synthesize</strong> sends
                  one query across all selected documents and returns a single
                  combined answer with citations from every contributing file —
                  best for cross-document questions.
                </>
              )}
            </p>
          </div>

          <div>
            <label
              htmlFor="batch-question"
              className="mb-2 block text-sm font-medium"
            >
              Question
            </label>
            <textarea
              id="batch-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={3}
              placeholder={
                mode === "synthesize"
                  ? "e.g. What's the expense process for visiting Apex Manufacturing, and are there known dashboard bugs?"
                  : "e.g. What are the key takeaways?"
              }
              className="w-full resize-y rounded-lg border border-border bg-surface px-4 py-3 text-base text-foreground outline-none focus:border-accent"
            />
          </div>

          <div>
            <p className="mb-2 text-sm font-medium">
              Documents{" "}
              <span className="font-normal text-muted">
                ({selected.size} selected)
              </span>
            </p>
            <ul className="flex flex-col gap-2">
              {documents.map((doc) => (
                <li key={doc.documentId}>
                  <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 transition-colors hover:border-accent">
                    <input
                      type="checkbox"
                      checked={selected.has(doc.documentId)}
                      onChange={() => toggle(doc.documentId)}
                      className="h-4 w-4 accent-[color:var(--accent)]"
                    />
                    <FileText size={16} className="shrink-0 text-muted" />
                    <span className="truncate text-sm">{doc.fileName}</span>
                    <span className="ml-auto truncate font-mono text-xs text-muted">
                      {doc.documentId.slice(0, 8)}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-accent px-5 py-2.5 font-medium text-surface transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {inflight && <Loader2 size={16} className="animate-spin" />}
              {inflight
                ? "Querying..."
                : mode === "compare"
                  ? "Run batch query"
                  : "Synthesize answer"}
            </button>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-500">
              <AlertCircle size={16} className="shrink-0" />
              {error}
            </div>
          )}

          {summary && mode === "compare" && (
            <div className="flex flex-wrap gap-4 rounded-lg border border-border bg-surface px-4 py-3 text-sm">
              <span>
                <strong>{summary.count}</strong> total
              </span>
              <span className="text-green-500">
                <strong>{summary.success}</strong> succeeded
              </span>
              <span className={summary.failure > 0 ? "text-red-500" : "text-muted"}>
                <strong>{summary.failure}</strong> failed
              </span>
            </div>
          )}

          {results && mode === "synthesize" && results[0] && (
            <BatchResultCard result={results[0]} title={synthesizeTitle} />
          )}

          {results && mode === "compare" && (
            <div className="grid gap-4 md:grid-cols-2">
              {results.map((result, index) => {
                const docId = result.doc_ids[0];
                const name =
                  (docId && nameById.get(docId)) || docId || "Unknown document";

                return (
                  <BatchResultCard
                    key={`${docId ?? "doc"}-${index}`}
                    result={result}
                    title={name}
                  />
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

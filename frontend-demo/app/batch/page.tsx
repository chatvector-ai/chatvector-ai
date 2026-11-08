"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Layers, Loader2, FileText } from "lucide-react";
import {
  deleteDocument,
  sendBatchMessage,
  sendConfigurationCompareBatchMessage,
  sendSynthesizedBatchMessage,
  listDocuments,
  type BatchResultItem,
  type DocumentSummary,
} from "../lib/api";
import { apiErrorMessage } from "../lib/apiErrorMessage";
import {
  batchSelectionLimit,
  batchSelectionWithinLimit,
  canAddBatchSelection,
} from "../lib/batchLimits";
import { BatchResultCard } from "../components/batch/BatchResultCard";
import BatchPageSkeleton from "../components/batch/BatchPageSkeleton";
import RetrievalSettingsPanel from "../components/RetrievalSettingsPanel";
import RetrievalOverrideEditor, {
  emptyRetrievalOverrideDraft,
} from "../components/RetrievalOverrideEditor";
import type { RetrievalOverrideDraft } from "../lib/retrievalRequestOverrides";
import BatchResultSkeleton from "./BatchResultSkeleton";
import DocumentListRow from "../components/DocumentListRow";
import {
  documentFailureDetail,
  fileTypeFromFileName,
  isDocumentInActiveScope,
} from "../lib/documentListDisplay";
import { EmptyState } from "../components/ui/EmptyState";
import { InfoPopover } from "../components/ui/InfoPopover";
import { InlineAlert } from "../components/ui/InlineAlert";
import { SegmentedControl } from "../components/ui/SegmentedControl";
import { useRetrievalSettings } from "../lib/hooks/useRetrievalSettings";
import UploadModal from "../components/UploadModal";
import { getSessionId } from "../lib/session";

type BatchDocument = DocumentSummary;

type BatchMode = "compare" | "synthesize" | "config-compare";

type ActiveBatchRequest = {
  mode: BatchMode;
  docIds: string[];
  question: string;
};

const BATCH_MODE_OPTIONS: { value: BatchMode; label: string }[] = [
  { value: "compare", label: "Compare" },
  { value: "synthesize", label: "Synthesize" },
  { value: "config-compare", label: "Config compare" },
];

export default function BatchPage() {
  const [documents, setDocuments] = useState<BatchDocument[]>([]);
  const [documentsLoaded, setDocumentsLoaded] = useState(false);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const { settings, setMatchCount, loaded: retrievalLoaded } = useRetrievalSettings();
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
  const [activeRequest, setActiveRequest] = useState<ActiveBatchRequest | null>(
    null,
  );
  const [replaceDocumentId, setReplaceDocumentId] = useState<string | null>(null);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [documentsRefreshKey, setDocumentsRefreshKey] = useState(0);
  const [configA, setConfigA] = useState<RetrievalOverrideDraft>(
    emptyRetrievalOverrideDraft(),
  );
  const [configB, setConfigB] = useState<RetrievalOverrideDraft>(
    emptyRetrievalOverrideDraft(),
  );
  const inflightRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function loadDocuments() {
      setDocumentsLoaded(false);
      setDocumentsError(null);
      try {
        const response = await listDocuments();
        if (cancelled) return;
        setDocuments(response.documents);
      } catch (err) {
        if (cancelled) return;
        setDocuments([]);
        setDocumentsError(
          apiErrorMessage(
            err,
            "Could not load documents. Check your connection and try again.",
          ),
        );
      } finally {
        if (!cancelled) {
          setDocumentsLoaded(true);
        }
      }
    }

    void loadDocuments();
    return () => {
      cancelled = true;
    };
  }, [documentsRefreshKey]);

  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const doc of documents) map.set(doc.document_id, doc.file_name);
    return map;
  }, [documents]);

  const selectedDocIds = useMemo(
    () => documents.map((d) => d.document_id).filter((id) => selected.has(id)),
    [documents, selected]
  );

  const reloadDocuments = () => {
    setDocumentsRefreshKey((key) => key + 1);
  };

  const handleReplaceDocument = (documentId: string) => {
    setReplaceDocumentId(documentId);
    setShowUploadModal(true);
  };

  const handleDeleteDocument = async (documentId: string) => {
    if (inflight) return;
    try {
      const out = await deleteDocument(documentId);
      if (out.status === "gone") {
        setSelected((prev) => {
          if (!prev.has(documentId)) return prev;
          const next = new Set(prev);
          next.delete(documentId);
          return next;
        });
        reloadDocuments();
      }
    } catch {
      // Best-effort row action; batch query errors surface separately.
    }
  };

  const selectionLimit = batchSelectionLimit(mode);
  const selectionLimitReached = selected.size >= selectionLimit;

  const synthesizeTitle = useMemo(() => {
    const docIds = activeRequest?.docIds ?? selectedDocIds;
    if (docIds.length === 1) {
      const docId = docIds[0];
      return nameById.get(docId) ?? docId;
    }
    return `Across ${docIds.length} documents`;
  }, [activeRequest?.docIds, selectedDocIds, nameById]);

  const toggle = (documentId: string) => {
    if (inflight) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(documentId)) {
        next.delete(documentId);
        return next;
      }
      if (!canAddBatchSelection(mode, next.size)) {
        return prev;
      }
      next.add(documentId);
      return next;
    });
  };

  const canSubmit =
    question.trim().length > 0 &&
    batchSelectionWithinLimit(mode, selected.size) &&
    !inflight;

  const handleSubmit = async () => {
    if (!canSubmit || inflightRef.current) return;

    const request: ActiveBatchRequest = {
      mode,
      docIds: selectedDocIds,
      question: question.trim(),
    };

    inflightRef.current = true;
    setActiveRequest(request);
    setError(null);
    setResults(null);
    setSummary(null);
    setInflight(true);
    try {
      const response =
        request.mode === "compare"
          ? await sendBatchMessage(request.question, request.docIds, {
              matchCount: settings.matchCount,
              scope: "session",
            })
          : request.mode === "synthesize"
            ? await sendSynthesizedBatchMessage(request.question, request.docIds, {
                matchCount: settings.matchCount,
                scope: "session",
              })
            : await sendConfigurationCompareBatchMessage(
                request.question,
                request.docIds,
                configA,
                configB,
              );
      setResults(response.results);
      setSummary({
        count: response.count,
        success: response.success_count,
        failure: response.failure_count,
      });
    } catch (e) {
      setError(
        apiErrorMessage(e, "Something went wrong. Please try again."),
      );
    } finally {
      inflightRef.current = false;
      setInflight(false);
    }
  };

  const renderMode = activeRequest?.mode ?? mode;
  const renderDocIds = activeRequest?.docIds ?? selectedDocIds;

  return (
    <div
      className="mx-auto w-full max-w-4xl px-4 py-10 text-foreground"
      aria-busy={!documentsLoaded || !retrievalLoaded}
    >
      {showUploadModal && (
        <UploadModal
          sessionId={getSessionId()}
          replaceDocumentId={replaceDocumentId}
          onClose={() => {
            setShowUploadModal(false);
            setReplaceDocumentId(null);
          }}
          onUploadAccepted={() => {
            setShowUploadModal(false);
            setReplaceDocumentId(null);
            reloadDocuments();
          }}
          attachment={null}
        />
      )}
      <div className="mb-8">
        <div className="flex items-center gap-2 text-accent-text">
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

      {!documentsLoaded || !retrievalLoaded ? (
        <BatchPageSkeleton />
      ) : documents.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No documents yet."
          description={
            documentsError ??
            "Upload a document on the chat page first — it'll show up here automatically."
          }
          action={documentsError ? undefined : { href: "/chat", label: "Go to chat" }}
        />
      ) : (
        <div className="flex flex-col gap-6">
          <div>
            <div className="mb-2 flex items-center gap-1.5">
              <p className="text-sm font-medium">Mode</p>
              <InfoPopover label="Batch mode help">
                <p>
                  <strong className="font-medium text-foreground/80">Compare</strong>{" "}
                  sends one query per document and shows a separate answer card for
                  each — useful for seeing what each file contributes. Each document
                  is answered independently from its own retrieved content; prior
                  chat or batch turns in this session are not used. Up to{" "}
                  {batchSelectionLimit("compare")} documents per batch.
                </p>
                <p className="mt-3">
                  <strong className="font-medium text-foreground/80">Synthesize</strong>{" "}
                  sends one query across all selected documents and returns a single
                  combined answer with citations from every contributing file — best
                  for cross-document questions. Up to{" "}
                  {batchSelectionLimit("synthesize")} documents per query.
                </p>
                <p className="mt-3">
                  <strong className="font-medium text-foreground/80">
                    Config compare
                  </strong>{" "}
                  runs one question across the same selected documents under two
                  explicit retrieval configurations and shows both answers side by side.
                  This is a reference view, not the eval CLI. Up to{" "}
                  {batchSelectionLimit("config-compare")} documents per run.
                </p>
              </InfoPopover>
            </div>
            <SegmentedControl
              name="batch-mode"
              ariaLabel="Batch query mode"
              value={mode}
              onChange={setMode}
              options={BATCH_MODE_OPTIONS}
              disabled={inflight}
            />
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
              disabled={inflight}
              placeholder={
                mode === "synthesize"
                  ? "e.g. What's the expense process for visiting Apex Manufacturing, and are there known dashboard bugs?"
                  : "e.g. What are the key takeaways?"
              }
              className="w-full resize-y rounded-lg border border-border bg-surface px-4 py-3 text-base text-foreground outline-none focus:border-accent disabled:opacity-50"
            />
          </div>

          <div>
            <p className="mb-2 text-sm font-medium">
              Documents{" "}
              <span className="font-normal text-muted">
                ({selected.size} selected · limit {selectionLimit})
              </span>
            </p>
            {selectionLimitReached && (
              <p className="mb-2 text-xs text-amber-400">
                {mode === "compare"
                  ? `Compare mode supports up to ${selectionLimit} documents per batch.`
                  : `Synthesize mode supports up to ${selectionLimit} documents per query.`}
              </p>
            )}
            <ul className="flex flex-col gap-2">
              {documents.map((doc) => {
                const processing =
                  doc.status !== "completed" && doc.status !== "failed";
                const inActiveScope = isDocumentInActiveScope({
                  scope: "tenant",
                  scopeIsExplicit: true,
                  selectedDocumentId: null,
                  documentId: doc.document_id,
                  status: doc.status,
                });
                return (
                  <li key={doc.document_id}>
                    <DocumentListRow
                      documentId={doc.document_id}
                      fileName={doc.file_name}
                      fileType={fileTypeFromFileName(doc.file_name)}
                      status={doc.status}
                      failureDetail={documentFailureDetail(doc.status, doc.error)}
                      metadata={doc.metadata}
                      inActiveScope={inActiveScope}
                      onReplace={
                        processing
                          ? undefined
                          : () => handleReplaceDocument(doc.document_id)
                      }
                      onDelete={() => void handleDeleteDocument(doc.document_id)}
                      disabled={inflight}
                      leading={
                        <input
                          type="checkbox"
                          checked={selected.has(doc.document_id)}
                          onChange={() => toggle(doc.document_id)}
                          disabled={
                            inflight ||
                            (!selected.has(doc.document_id) &&
                              selectionLimitReached)
                          }
                          className="mt-1 h-4 w-4 accent-[color:var(--accent)]"
                          aria-label={`Select ${doc.file_name}`}
                        />
                      }
                    />
                  </li>
                );
              })}
            </ul>
          </div>

          {mode === "config-compare" ? (
            <div className="space-y-3">
              <p className="text-sm text-muted">
                Reference comparison only — not the eval CLI and experiments are not
                saved. Set only the retrieval fields each side should override; omitted
                fields stay on process defaults.
              </p>
              <div className="grid gap-4 md:grid-cols-2">
                <RetrievalOverrideEditor
                  title="Configuration A"
                  draft={configA}
                  onChange={setConfigA}
                  disabled={inflight}
                />
                <RetrievalOverrideEditor
                  title="Configuration B"
                  draft={configB}
                  onChange={setConfigB}
                  disabled={inflight}
                />
              </div>
            </div>
          ) : (
            <RetrievalSettingsPanel
              settings={settings}
              onMatchCountChange={setMatchCount}
              showScope={false}
            />
          )}

          <div>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-accent px-5 py-2.5 font-medium text-accent-foreground transition-colors hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {inflight && <Loader2 size={16} className="animate-spin" />}
              {inflight
                ? "Querying..."
                : mode === "compare"
                  ? "Run batch query"
                  : mode === "synthesize"
                    ? "Synthesize answer"
                    : "Compare configurations"}
            </button>
          </div>

          {error && <InlineAlert>{error}</InlineAlert>}

          {summary && renderMode === "compare" && (
            <div className="flex flex-wrap gap-4 rounded-lg border border-border bg-surface px-4 py-3 text-sm">
              <span>
                <strong>{summary.count}</strong> total
              </span>
              <span className="text-accent-text">
                <strong>{summary.success}</strong> succeeded
              </span>
              <span className={summary.failure > 0 ? "text-red-500" : "text-muted"}>
                <strong>{summary.failure}</strong> failed
              </span>
            </div>
          )}

          <div aria-busy={inflight}>
            {inflight && renderMode === "synthesize" && <BatchResultSkeleton />}

            {inflight && renderMode === "compare" && (
              <div className="grid gap-4 md:grid-cols-2">
                {Array.from({ length: renderDocIds.length }).map((_, index) => (
                  <BatchResultSkeleton key={index} />
                ))}
              </div>
            )}

            {inflight && renderMode === "config-compare" && (
              <div className="grid gap-4 md:grid-cols-2">
                <BatchResultSkeleton />
                <BatchResultSkeleton />
              </div>
            )}

            {!inflight && results && renderMode === "synthesize" && results[0] && (
              <BatchResultCard result={results[0]} title={synthesizeTitle} />
            )}

            {!inflight && results && renderMode === "config-compare" && (
              <div className="grid gap-4 md:grid-cols-2">
                {results.slice(0, 2).map((result, index) => (
                  <BatchResultCard
                    key={`config-${index}`}
                    result={result}
                    title={index === 0 ? "Configuration A" : "Configuration B"}
                  />
                ))}
              </div>
            )}

            {!inflight && results && renderMode === "compare" && (
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
        </div>
      )}
    </div>
  );
}

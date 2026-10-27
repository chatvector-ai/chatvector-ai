"use client";

import { useRef, useState, useEffect, type RefObject } from "react";
import { X, Upload, AlertCircle, FileText, Loader2 } from "lucide-react";
import { uploadDocument } from "../lib/api";
import IngestionPipeline from "./IngestionPipeline";

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.offsetParent !== null || el.getClientRects().length > 0,
  );
}

export type UploadAcceptedPayload = {
  fileName: string;
  documentId: string;
  statusEndpoint: string;
  queuePosition?: number;
};

export type UploadModalAttachment = {
  documentId?: string;
  status: "processing" | "ready" | "failed";
  stage?: string;
  chunks?: { total: number; processed: number };
  processingTime?: string;
  errorMessage?: string;
};

type Props = {
  onClose: () => void;
  /** Active chat session — binds the upload to session restore on navigation/refresh. */
  sessionId?: string | null;
  /** Element to return focus to when the modal closes. */
  returnFocusRef?: RefObject<HTMLElement | null>;
  /** Document ID of an existing ready/failed attachment to replace in place on POST /upload. */
  replaceDocumentId?: string | null;
  /** Run before POST /upload (e.g. delete the prior document so replacement does not orphan rows). */
  onBeforeUpload?: () => Promise<void>;
  onUploadAccepted: (payload: UploadAcceptedPayload) => void;
  /** Reflects server-side processing for the active upload; used after POST /upload succeeds. */
  attachment: UploadModalAttachment | null;
};

export default function UploadModal({
  onClose,
  sessionId,
  returnFocusRef,
  replaceDocumentId,
  onBeforeUpload,
  onUploadAccepted,
  attachment,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [lastFile, setLastFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadHttpFailed, setUploadHttpFailed] = useState(false);
  const [uploadErrorMessage, setUploadErrorMessage] = useState<string | null>(
    null,
  );
  /** Until parent `attachment` reflects the new doc, avoid flashing the file picker after POST succeeds. */
  const [awaitingProcessing, setAwaitingProcessing] = useState(false);
  /** Tracks whether an upload in this modal session has started or was already processing on open. */
  const [hasActiveUpload, setHasActiveUpload] = useState(
    attachment?.status === "processing"
  );
  /** Tracks whether the pipeline animation has visually reached "completed". */
  const [pipelineVisuallyComplete, setPipelineVisuallyComplete] =
    useState(false);

  const effectiveReplaceDocumentId =
    replaceDocumentId !== undefined
      ? replaceDocumentId
      : attachment &&
          (attachment.status === "ready" || attachment.status === "failed")
        ? (attachment.documentId ?? null)
        : null;

  useEffect(() => {
    if (attachment?.status === "processing") {
      setHasActiveUpload(true);
    }
    if (
      attachment?.status === "processing" ||
      attachment?.status === "ready" ||
      attachment?.status === "failed"
    ) {
      setAwaitingProcessing(false);
    }
  }, [attachment?.status]);

  const hasServerError =
    attachment?.status === "failed" || Boolean(attachment?.errorMessage);
  const showSuccess =
    hasActiveUpload && attachment?.status === "ready" && !hasServerError;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    closeButtonRef.current?.focus();
    const returnFocusElement = returnFocusRef?.current ?? null;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }

      if (event.key !== "Tab") return;

      const focusable = getFocusableElements(dialogRef.current);
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      returnFocusElement?.focus();
    };
  }, [returnFocusRef]);

  // Start the close timer only once the pipeline animation visually reaches
  // "completed" — this guarantees the 1.5s border sweep has its full duration.
  useEffect(() => {
    if (!pipelineVisuallyComplete) return;
    const timer = setTimeout(() => onCloseRef.current(), 1500);
    return () => clearTimeout(timer);
  }, [pipelineVisuallyComplete]);

  const handleFile = async (file: File) => {
    setLastFile(file);
    setIsUploading(true);
    setUploadHttpFailed(false);
    setUploadErrorMessage(null);
    setPipelineVisuallyComplete(false);
    try {
      if (onBeforeUpload) {
        await onBeforeUpload();
      }
      const { documentId, statusEndpoint, queuePosition } =
        effectiveReplaceDocumentId
          ? await uploadDocument(file, sessionId, effectiveReplaceDocumentId)
          : await uploadDocument(file, sessionId);
      setHasActiveUpload(true);
      onUploadAccepted({
        fileName: file.name,
        documentId,
        statusEndpoint,
        queuePosition,
      });
      setAwaitingProcessing(true);
    } catch (err) {
      setUploadHttpFailed(true);
      setUploadErrorMessage(err instanceof Error ? err.message : null);
      setAwaitingProcessing(false);
    } finally {
      setIsUploading(false);
    }
  };

  const handleRetry = () => {
    if (lastFile) {
      void handleFile(lastFile);
    } else {
      inputRef.current?.click();
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  /** HTTP-level failure: POST /upload itself returned an error. */
  const showHttpFailed = !isUploading && uploadHttpFailed;
  /** Server-side processing failure: document reached a failed state after upload succeeded. */
  const showServerFailed =
    hasActiveUpload &&
    !isUploading &&
    !awaitingProcessing &&
    !uploadHttpFailed &&
    hasServerError;
  const showFailed = showHttpFailed || showServerFailed;

  const showProcessing =
    !showFailed &&
    !isUploading &&
    !showSuccess &&
    (attachment?.status === "processing" || awaitingProcessing);
  const showUploading = isUploading;
  const showPicker =
    !showUploading &&
    !showProcessing &&
    !showFailed &&
    !showSuccess &&
    (attachment === null ||
      attachment.status === "ready" ||
      attachment.status === "failed");

  const dropZoneInteractive = showPicker;
  // Keep "Dismiss and wait" visible until the animation visually reaches "completed",
  // not just when the raw SSE status flips to ready.
  const showDismissWait =
    (showUploading || showProcessing || showSuccess) &&
    !pipelineVisuallyComplete;

  const showPipeline =
    showUploading || showProcessing || showSuccess || showServerFailed;

  const dropZoneClassName = [
    "relative rounded-2xl border-2 border-dashed transition-all duration-300 ease-out",
    showPipeline
      ? "border-border bg-background px-6 py-5"
      : "min-h-[200px] p-10 flex flex-col items-center justify-center",
    showHttpFailed
      ? "border-red-500/25 bg-red-500/[0.04]"
      : dropZoneInteractive
        ? "border-border bg-surface hover:border-accent hover:bg-accent/5 cursor-pointer active:scale-[0.99]"
        : showPipeline
          ? ""
          : "border-border bg-background",
  ].join(" ");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
      style={{
        backgroundColor: "color-mix(in srgb, var(--background) 72%, transparent)",
        backdropFilter: "blur(10px)",
      }}
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-modal-title"
        className="relative w-full max-w-[460px] rounded-3xl border border-border bg-surface p-6 shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        {pipelineVisuallyComplete && (
          <>
            <style>{`
              @property --border-sweep {
                syntax: '<angle>';
                initial-value: 0deg;
                inherits: false;
              }
              @keyframes border-sweep {
                to { --border-sweep: 360deg; }
              }
              .modal-border-sweep {
                animation: border-sweep 1.45s linear forwards;
                background: conic-gradient(
                  from 180deg at 50% 50%,
                  var(--success) 0deg,
                  var(--success) var(--border-sweep),
                  transparent var(--border-sweep)
                );
                -webkit-mask:
                  linear-gradient(#fff 0 0) content-box,
                  linear-gradient(#fff 0 0);
                -webkit-mask-composite: destination-out;
                mask-composite: exclude;
                padding: 10px;
              }
            `}</style>
            <div
              className="modal-border-sweep pointer-events-none absolute inset-0 rounded-3xl"
              aria-hidden
            />
          </>
        )}
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h2
                id="upload-modal-title"
                className="text-xl font-semibold tracking-tight text-foreground"
              >
                Upload document
              </h2>
              {showDismissWait && (
                <button
                  type="button"
                  onClick={onClose}
                  className="inline-flex items-center justify-center rounded-lg px-2.5 py-1 text-sm font-medium text-muted transition hover:bg-background hover:text-foreground"
                >
                  Dismiss and wait
                </button>
              )}
            </div>
            <p className="mt-1 mb-2 text-base text-muted">
              PDF, TXT, Markdown, HTML, and DOCX
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            className="rounded-xl p-2 text-muted transition-colors hover:bg-background hover:text-foreground"
            aria-label="Close"
          >
            <X size={20} strokeWidth={1.75} />
          </button>
        </div>

        <div
          onDrop={dropZoneInteractive ? handleDrop : (e) => e.preventDefault()}
          onDragOver={(e) => e.preventDefault()}
          onClick={() => dropZoneInteractive && inputRef.current?.click()}
          onKeyDown={
            dropZoneInteractive
              ? (e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    inputRef.current?.click();
                  }
                }
              : undefined
          }
          role={dropZoneInteractive ? "button" : undefined}
          tabIndex={dropZoneInteractive ? 0 : undefined}
          aria-label={
            dropZoneInteractive
              ? "Upload document — drop a file or press Enter to browse"
              : undefined
          }
          className={dropZoneClassName}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.txt,.md,.markdown,.html,.htm,.docx"
            onChange={handleChange}
            className="hidden"
          />
          {showPipeline && (
            <div className="flex gap-0">
              {/* Left — stage list */}
              <div className="w-40 shrink-0">
                <IngestionPipeline
                  currentStage={showUploading ? "uploading" : attachment?.stage}
                  failed={showServerFailed}
                  chunks={attachment?.chunks}
                  errorMessage={attachment?.errorMessage}
                  onDisplayedStageChange={(s) => {
                    if (s === "completed") setPipelineVisuallyComplete(true);
                  }}
                />
                {showServerFailed && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRetry();
                    }}
                    className="mt-2 w-full rounded-full border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition hover:bg-surface"
                  >
                    Retry
                  </button>
                )}
              </div>

              {/* Right — document status panel */}
              <div className="flex w-48 shrink-0 flex-col items-center justify-center gap-4 text-center">
                {pipelineVisuallyComplete ? (
                  <>
                    <div className="flex h-24 w-24 items-center justify-center rounded-full bg-success/15 ring-2 ring-success/30">
                      <svg
                        width="44"
                        height="44"
                        viewBox="0 0 20 20"
                        fill="none"
                        aria-hidden
                        className="text-success"
                      >
                        <path
                          d="M4 10l4.5 4.5L16 6"
                          stroke="currentColor"
                          strokeWidth="2.25"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </div>
                    <p className="text-base font-semibold leading-snug text-success-text">
                      Upload
                      <br />
                      Successful
                    </p>
                    {attachment?.processingTime && (
                      <p className="text-xs text-muted">Processed in {attachment.processingTime}</p>
                    )}
                  </>
                ) : (
                  <>
                    <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-info/10 ring-1 ring-info/20">
                      <FileText
                        size={28}
                        className="text-info"
                        strokeWidth={1.75}
                        aria-hidden
                      />
                    </div>
                    <p
                      className="w-full truncate text-sm font-medium text-foreground"
                      title={lastFile?.name}
                    >
                      {lastFile?.name ?? "Document"}
                    </p>
                    {!showServerFailed ? (
                      <Loader2
                        size={28}
                        className="animate-spin text-accent"
                        strokeWidth={2}
                        aria-hidden
                      />
                    ) : (
                      <>
                        <AlertCircle
                          size={28}
                          className="text-danger"
                          strokeWidth={2}
                          aria-hidden
                        />
                        {attachment?.errorMessage && (
                          <p className="text-xs text-danger-text/90">
                            {attachment.errorMessage.slice(0, 80)}
                          </p>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
          {showHttpFailed && (
            <div className="flex flex-col items-center gap-4 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-danger/10 ring-1 ring-danger/20">
                <AlertCircle
                  className="h-7 w-7 text-danger"
                  strokeWidth={1.75}
                  aria-hidden
                />
              </div>
              <p className="max-w-[280px] whitespace-pre-wrap text-base font-medium text-danger-text">
                {uploadErrorMessage ?? "Upload failed. Please try again."}
              </p>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleRetry();
                }}
                className="rounded-full border border-border bg-background px-4 py-2 text-base font-medium text-foreground transition hover:bg-surface"
              >
                Retry
              </button>
            </div>
          )}
          {showPicker && (
            <>
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-background ring-1 ring-border">
                <Upload className="h-7 w-7 text-muted" strokeWidth={1.5} />
              </div>
              <p className="max-w-[280px] text-center text-base text-muted">
                Drop a file here or{" "}
                <span className="font-medium text-accent-text">browse</span>
              </p>
              <p className="mt-2 text-sm text-subtle">
                PDF · TXT · Markdown · HTML · DOCX
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

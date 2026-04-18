"use client";

import { useRef, useState, useEffect } from "react";
import { X, Upload, Loader2, AlertCircle } from "lucide-react";
import { uploadDocument } from "../lib/api";
import { STAGE_LABELS } from "../lib/stageLabels";

export type UploadAcceptedPayload = {
  fileName: string;
  documentId: string;
  statusEndpoint: string;
};

export type UploadModalAttachment = {
  status: "processing" | "ready" | "failed";
  stage?: string;
  chunks?: { total: number; processed: number };
};

type Props = {
  onClose: () => void;
  /** Run before POST /upload (e.g. delete the prior document so replacement does not orphan rows). */
  onBeforeUpload?: () => Promise<void>;
  onUploadAccepted: (payload: UploadAcceptedPayload) => void;
  /** Reflects server-side processing for the active upload; used after POST /upload succeeds. */
  attachment: UploadModalAttachment | null;
};

export default function UploadModal({
  onClose,
  onBeforeUpload,
  onUploadAccepted,
  attachment,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [lastFile, setLastFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadHttpFailed, setUploadHttpFailed] = useState(false);
  /** Until parent `attachment` reflects the new doc, avoid flashing the file picker after POST succeeds. */
  const [awaitingProcessing, setAwaitingProcessing] = useState(false);

  useEffect(() => {
    if (
      attachment?.status === "processing" ||
      attachment?.status === "ready" ||
      attachment?.status === "failed"
    ) {
      setAwaitingProcessing(false);
    }
  }, [attachment?.status]);

  const showSuccess = attachment?.status === "ready";
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!showSuccess) return;
    const timer = setTimeout(() => onCloseRef.current(), 1500);
    return () => clearTimeout(timer);
  }, [showSuccess]);

  const handleFile = async (file: File) => {
    setLastFile(file);
    setIsUploading(true);
    setUploadHttpFailed(false);
    try {
      if (onBeforeUpload) {
        await onBeforeUpload();
      }
      const { documentId, statusEndpoint } = await uploadDocument(file);
      onUploadAccepted({ fileName: file.name, documentId, statusEndpoint });
      setAwaitingProcessing(true);
    } catch {
      setUploadHttpFailed(true);
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

  const showFailed =
    !isUploading && (uploadHttpFailed || attachment?.status === "failed");
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
    (attachment === null || attachment.status === "ready");

  const dropZoneInteractive = showPicker;
  const showDismissWait = (showUploading || showProcessing) && !showSuccess;

  const dropZoneClassName = [
    "relative min-h-[200px] rounded-2xl border-2 border-dashed p-10 flex flex-col items-center justify-center transition-all duration-300 ease-out",
    showSuccess
      ? "border-emerald-500/40 bg-emerald-500/[0.07]"
      : showFailed
        ? "border-red-500/25 bg-red-500/[0.04]"
        : dropZoneInteractive
          ? "border-border bg-surface hover:border-accent hover:bg-accent/5 cursor-pointer active:scale-[0.99]"
          : "border-border bg-background",
  ].join(" ");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
      style={{
        backgroundColor: "rgba(2, 6, 23, 0.72)",
        backdropFilter: "blur(10px)",
      }}
    >
      <div
        className="w-full max-w-[460px] rounded-3xl border border-border bg-surface p-6 shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              Upload document
            </h2>
            <p className="mt-1 text-base text-muted">PDF, TXT, or DOCX</p>
            <div className="mt-1 flex min-h-[2.5rem] items-center">
              <button
                type="button"
                onClick={onClose}
                tabIndex={showDismissWait ? 0 : -1}
                aria-hidden={!showDismissWait}
                className={`inline-flex items-center justify-center rounded-lg px-3.5 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue/50 ${
                  showDismissWait
                    ? "cursor-pointer text-muted hover:bg-background hover:text-foreground"
                    : "pointer-events-none invisible"
                }`}
              >
                Dismiss and wait
              </button>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl p-2 text-muted transition-colors hover:bg-background hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-border"
            aria-label="Close"
          >
            <X size={20} strokeWidth={1.75} />
          </button>
        </div>

        <div
          onDrop={dropZoneInteractive ? handleDrop : (e) => e.preventDefault()}
          onDragOver={(e) => e.preventDefault()}
          onClick={() => dropZoneInteractive && inputRef.current?.click()}
          className={dropZoneClassName}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.txt,.docx"
            onChange={handleChange}
            className="hidden"
          />
          {showUploading && (
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue/10 ring-1 ring-blue/20">
                <Loader2 className="h-7 w-7 animate-spin text-blue" strokeWidth={2} />
              </div>
              <p className="text-base font-medium text-foreground">Uploading…</p>
            </div>
          )}
          {showProcessing && (
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-blue/10 ring-1 ring-blue/20">
                <Loader2 className="h-7 w-7 animate-spin text-blue" strokeWidth={2} />
              </div>
              <p className="max-w-[280px] text-center text-base font-medium leading-snug text-foreground">
                {attachment?.stage
                  ? STAGE_LABELS[attachment.stage] ?? attachment.stage
                  : "Processing your document…"}
                {attachment?.stage === "embedding" && attachment?.chunks?.total
                  ? ` (${attachment.chunks.total} chunks)`
                  : ""}
              </p>
            </div>
          )}
          {showFailed && (
            <div className="flex flex-col items-center gap-4 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-red-500/10 ring-1 ring-red-500/20">
                <AlertCircle className="h-7 w-7 text-red-400" strokeWidth={1.75} aria-hidden />
              </div>
              <p className="max-w-[280px] text-base font-medium text-red-400">
                Upload failed. Please try again.
              </p>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleRetry();
                }}
                className="rounded-full border border-border bg-background px-4 py-2 text-base font-medium text-foreground transition hover:bg-surface focus:outline-none focus-visible:ring-2 focus-visible:ring-blue/50"
              >
                Retry
              </button>
            </div>
          )}
          {showSuccess && (
            <div className="flex flex-col items-center gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/15 ring-1 ring-emerald-400/25">
                <svg width="22" height="22" viewBox="0 0 20 20" fill="none" aria-hidden>
                  <path
                    d="M4 10l4.5 4.5L16 6"
                    stroke="#34d399"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
              <p className="text-base font-semibold text-emerald-400">Document ready!</p>
            </div>
          )}
          {showPicker && (
            <>
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-background ring-1 ring-border">
                <Upload className="h-7 w-7 text-muted" strokeWidth={1.5} />
              </div>
              <p className="max-w-[280px] text-center text-base text-muted">
                Drop a file here or{" "}
                <span className="font-medium text-accent">browse</span>
              </p>
              <p className="mt-2 text-sm text-subtle">PDF · TXT · DOCX</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

"use client";

import { useRef, useState, useEffect } from "react";
import { X, Upload, AlertCircle } from "lucide-react";
import { uploadDocument } from "../lib/api";
import IngestionPipeline from "./IngestionPipeline";

export type UploadAcceptedPayload = {
  fileName: string;
  documentId: string;
  statusEndpoint: string;
};

export type UploadModalAttachment = {
  status: "processing" | "ready" | "failed";
  stage?: string;
  completedStages?: string[];
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
    const timer = setTimeout(() => onCloseRef.current(), 2500);
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

  /** HTTP-level failure: POST /upload itself returned an error. */
  const showHttpFailed = !isUploading && uploadHttpFailed;
  /** Server-side processing failure: document reached a failed state after upload succeeded. */
  const showServerFailed =
    !isUploading && !uploadHttpFailed && attachment?.status === "failed";
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
    (attachment === null || attachment.status === "ready");

  const dropZoneInteractive = showPicker;
  const showDismissWait = (showUploading || showProcessing) && !showSuccess;

  const showPipeline = showUploading || showProcessing || showSuccess || showServerFailed;

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
                className={`inline-flex items-center justify-center rounded-lg px-3.5 py-2 text-sm font-medium transition ${
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
            accept=".pdf,.txt,.docx"
            onChange={handleChange}
            className="hidden"
          />
          {showPipeline && (
            <IngestionPipeline
              currentStage={showUploading ? "uploading" : attachment?.stage}
              completedStages={
                showUploading
                  ? []
                  : (attachment?.completedStages ?? [])
              }
              failed={showServerFailed}
              chunks={attachment?.chunks}
            />
          )}
          {showServerFailed && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleRetry();
              }}
              className="mt-4 w-full rounded-full border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition hover:bg-surface"
            >
              Retry
            </button>
          )}
          {showHttpFailed && (
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

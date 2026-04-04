"use client";

import { useRef, useState, useEffect } from "react";
import { X, Upload, Loader2 } from "lucide-react";
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
    (attachment?.status === "processing" || awaitingProcessing);
  const showUploading = isUploading;
  const showPicker =
    !showUploading && !showProcessing && !showFailed && (attachment === null || attachment.status === "ready");

  const dropZoneInteractive = showPicker;
  const showDismissWait = showUploading || showProcessing;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 rounded-2xl p-6 w-full max-w-md mx-4 border border-gray-700">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-white font-semibold text-lg">Upload Document</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X size={20} />
          </button>
        </div>
        <div
          onDrop={dropZoneInteractive ? handleDrop : (e) => e.preventDefault()}
          onDragOver={(e) => e.preventDefault()}
          onClick={() => dropZoneInteractive && inputRef.current?.click()}
          className={`border-2 border-dashed border-gray-600 rounded-xl p-10 flex flex-col items-center justify-center transition ${
            dropZoneInteractive ? "hover:border-indigo-500 cursor-pointer" : ""
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.txt,.docx"
            onChange={handleChange}
            className="hidden"
          />
          {showUploading && (
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="text-indigo-400 animate-spin" size={28} />
              <p className="text-indigo-400 text-sm">Uploading…</p>
            </div>
          )}
          {showProcessing && (
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="text-indigo-400 animate-spin" size={28} />
              <p className="text-indigo-400 text-sm">
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
            <div className="flex flex-col items-center gap-3 text-center">
              <p className="text-red-400 text-sm">Upload failed. Please try again.</p>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleRetry();
                }}
                className="text-sm text-indigo-400 hover:text-indigo-300"
              >
                Retry
              </button>
            </div>
          )}
          {showPicker && (
            <>
              <Upload size={32} className="text-gray-500 mb-3" />
              <p className="text-gray-400 text-sm text-center">
                Drag & drop or <span className="text-indigo-400">click to browse</span>
              </p>
              <p className="text-gray-600 text-xs mt-1">PDF, TXT, DOCX supported</p>
            </>
          )}
        </div>
        {showDismissWait && (
          <button
            type="button"
            onClick={onClose}
            className="mt-3 w-full text-center text-xs text-gray-500 hover:text-gray-400"
          >
            Dismiss and wait
          </button>
        )}
      </div>
    </div>
  );
}

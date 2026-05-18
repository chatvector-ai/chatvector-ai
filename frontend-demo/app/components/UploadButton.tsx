"use client";

import { Paperclip } from "lucide-react";

type Props = {
  onClick: () => void;
  disabled?: boolean;
};

export default function UploadButton({ onClick, disabled = false }: Props) {
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={`transition ${disabled ? "cursor-not-allowed text-muted/30" : "text-muted hover:text-foreground"}`}
      title={disabled ? "Remove the current document before uploading a new one" : "Upload document"}
      aria-label="Upload document"
    >
      <Paperclip size={18} />
    </button>
  );
}
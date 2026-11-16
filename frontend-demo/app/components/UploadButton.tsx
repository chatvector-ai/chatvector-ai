"use client";

import { Paperclip } from "lucide-react";
import { forwardRef } from "react";

type Props = {
  onClick: () => void;
  disabled?: boolean;
  label?: string;
};

const UploadButton = forwardRef<HTMLButtonElement, Props>(function UploadButton(
  { onClick, disabled = false, label = "Upload document" },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      className={`transition ${disabled ? "cursor-not-allowed text-muted/30" : "text-muted hover:text-foreground"}`}
      title={disabled ? "Wait for the current document to finish processing" : label}
      aria-label={label}
    >
      <Paperclip size={18} />
    </button>
  );
});

export default UploadButton;
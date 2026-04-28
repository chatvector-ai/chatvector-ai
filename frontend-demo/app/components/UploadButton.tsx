"use client";

import { Paperclip } from "lucide-react";

type Props = {
  onClick: () => void;
};

export default function UploadButton({ onClick }: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-muted hover:text-foreground transition"
      title="Upload document"
      aria-label="Upload document"
    >
      <Paperclip size={18} />
    </button>
  );
}
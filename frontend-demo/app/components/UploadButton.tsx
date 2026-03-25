"use client";

import { Paperclip } from "lucide-react";

type Props = {
  onClick: () => void;
};

export default function UploadButton({ onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className="text-gray-400 hover:text-white transition"
      title="Upload document"
    >
      <Paperclip size={18} />
    </button>
  );
}
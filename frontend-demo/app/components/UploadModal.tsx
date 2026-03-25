"use client";

import { useRef, useState } from "react";
import { X, Upload } from "lucide-react";

type Props = {
  onClose: () => void;
  onUploadSuccess: (fileName: string) => void;
};

export default function UploadModal({ onClose, onUploadSuccess }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [error, setError] = useState("");

  const handleFile = async (file: File) => {
    setStatus("uploading");
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("http://localhost:8000/upload", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error("Upload failed");
      setStatus("success");
      onUploadSuccess(file.name);
      setTimeout(() => onClose(), 1000);
    } catch {
      setStatus("error");
      setError("Upload failed. Please try again.");
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
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          onClick={() => inputRef.current?.click()}
          className="border-2 border-dashed border-gray-600 hover:border-indigo-500 rounded-xl p-10 flex flex-col items-center justify-center cursor-pointer transition"
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.txt,.docx"
            onChange={handleChange}
            className="hidden"
          />
          {status === "uploading" && <p className="text-indigo-400 text-sm animate-pulse">Uploading...</p>}
          {status === "success" && <p className="text-green-400 text-sm">✅ Upload successful!</p>}
          {status === "error" && <p className="text-red-400 text-sm">{error}</p>}
          {status === "idle" && (
            <>
              <Upload size={32} className="text-gray-500 mb-3" />
              <p className="text-gray-400 text-sm text-center">
                Drag & drop or <span className="text-indigo-400">click to browse</span>
              </p>
              <p className="text-gray-600 text-xs mt-1">PDF, TXT, DOCX supported</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
"use client";

import { useLayoutEffect, useRef } from "react";
import { Send } from "lucide-react";
import UploadButton from "../UploadButton";
import AttachmentChip from "../AttachmentChip";
import type { AttachmentState } from "../../lib/api";
import { useDocumentPolling } from "../../lib/hooks/useDocumentPolling";

const TEXTAREA_MIN_PX = 44;
const TEXTAREA_MAX_PX = 220;

type Props = {
  input: string;
  setInput: (v: string) => void;
  sendDisabled: boolean;
  inflight: boolean;
  attachment: AttachmentState | null;
  removeError: string | null;
  poll: ReturnType<typeof useDocumentPolling>;
  handleSend: () => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  handleRemoveAttachment: () => void;
  onUploadClick: () => void;
};

export default function ChatInput({
  input,
  setInput,
  sendDisabled,
  inflight,
  attachment,
  removeError,
  poll,
  handleSend,
  handleKeyDown,
  handleRemoveAttachment,
  onUploadClick,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    const h = Math.min(
      Math.max(el.scrollHeight, TEXTAREA_MIN_PX),
      TEXTAREA_MAX_PX
    );
    el.style.height = `${h}px`;
  }, [input]);

  return (
    <div className="shrink-0 bg-background">
      {attachment && (
        <div className="px-4 pt-2">
          <AttachmentChip
            fileName={attachment.fileName}
            status={attachment.status}
            stage={poll.stage}
            chunks={poll.chunks}
            awaitingProcessing={poll.awaitingProcessing}
            onRemove={() => void handleRemoveAttachment()}
          />
        </div>
      )}
      {attachment?.status === "processing" && (
        <p className="px-4 pb-1 text-xs text-amber-400 bg-background">
          Document still processing — sending is disabled until it is ready.
        </p>
      )}
      {removeError && (
        <p className="px-4 pb-1 text-xs text-red-400 bg-background">{removeError}</p>
      )}

      <div className="bg-background px-4 py-3">
        <div className="flex items-end gap-2 bg-surface rounded-xl px-4 py-2">
          <UploadButton onClick={onUploadClick} />
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              attachment?.status === "processing"
                ? "Waiting for document to be ready..."
                : "Ask about your document..."
            }
            disabled={inflight}
            aria-label="Message"
            className="min-h-[44px] max-h-[220px] flex-1 resize-none overflow-y-auto bg-transparent py-2.5 text-sm leading-snug text-foreground outline-none placeholder:text-muted disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => void handleSend()}
            disabled={sendDisabled}
            aria-label="Send message"
            title={
              inflight
                ? "Waiting for response..."
                : attachment?.status === "processing"
                  ? "Document still processing..."
                  : !input.trim()
                    ? "Type a message to send"
                    : undefined
            }
            className={`w-8 h-8 rounded-lg flex items-center justify-center transition ${
              sendDisabled
                ? "bg-surface cursor-not-allowed opacity-50"
                : "bg-accent hover:bg-accent/80 cursor-pointer text-background"
            }`}
          >
            <Send size={15} />
          </button>
        </div>
        <p className="text-center text-xs text-muted mt-2">
          ChatVector may make mistakes. Always verify important information.
        </p>
      </div>
    </div>
  );
}

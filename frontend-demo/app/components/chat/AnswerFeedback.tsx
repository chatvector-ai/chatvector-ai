"use client";

import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { submitAnswerFeedback } from "../../lib/api";

const COMMENT_MAX_LENGTH = 4096;

type Rating = 1 | -1;

type Props = {
  sessionId: string | null;
  messageId: string;
};

function feedbackErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  return "Could not save feedback.";
}

export default function AnswerFeedback({ sessionId, messageId }: Props) {
  const [comment, setComment] = useState("");
  const [savedRating, setSavedRating] = useState<Rating | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(rating: Rating) {
    if (pending) return;

    const trimmedSessionId = sessionId?.trim() ?? "";
    if (!trimmedSessionId) {
      setError("This answer is not attached to a session.");
      return;
    }

    setPending(true);
    setError(null);
    try {
      await submitAnswerFeedback({
        sessionId: trimmedSessionId,
        messageId,
        rating,
        comment,
      });
      setSavedRating(rating);
    } catch (submitError) {
      setError(feedbackErrorMessage(submitError));
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      className="mt-3 flex flex-col gap-2 border-t border-border pt-2"
      role="group"
      aria-label="Rate this answer"
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="Thumbs up"
          aria-pressed={savedRating === 1}
          disabled={pending}
          onClick={() => {
            void submit(1);
          }}
          className="inline-flex items-center justify-center rounded-md border border-border p-1.5 text-muted hover:text-foreground disabled:opacity-50 aria-pressed:bg-accent/15 aria-pressed:text-accent-text"
        >
          <ThumbsUp size={14} aria-hidden />
        </button>
        <button
          type="button"
          aria-label="Thumbs down"
          aria-pressed={savedRating === -1}
          disabled={pending}
          onClick={() => {
            void submit(-1);
          }}
          className="inline-flex items-center justify-center rounded-md border border-border p-1.5 text-muted hover:text-foreground disabled:opacity-50 aria-pressed:bg-accent/15 aria-pressed:text-accent-text"
        >
          <ThumbsDown size={14} aria-hidden />
        </button>
        {savedRating !== null && (
          <span role="status" className="px-1 text-xs text-muted">
            Saved
          </span>
        )}
      </div>
      <input
        type="text"
        value={comment}
        maxLength={COMMENT_MAX_LENGTH}
        onChange={(event) => setComment(event.target.value)}
        placeholder="Optional note"
        aria-label="Optional comment"
        disabled={pending}
        className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm text-foreground placeholder:text-muted"
      />
      {error && (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      )}
    </div>
  );
}

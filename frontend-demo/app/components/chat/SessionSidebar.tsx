"use client";

import { Trash2, X } from "lucide-react";
import type { ChatSession } from "../../lib/hooks/useSessionManager";

type Props = {
  sessions: ChatSession[];
  activeSessionId: string;
  onCreateSession: () => void;
  onSwitchSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  isCreating?: boolean;
  deletingSessionId?: string | null;
  isOpen?: boolean;
  onClose?: () => void;
  id?: string;
};

export default function SessionSidebar({
  sessions,
  activeSessionId,
  onCreateSession,
  onSwitchSession,
  onDeleteSession,
  isCreating = false,
  deletingSessionId = null,
  isOpen = false,
  onClose,
  id = "chat-session-sidebar",
}: Props) {
  return (
    <>
      {isOpen && onClose && (
        <div
          data-testid="session-sidebar-backdrop"
          className="absolute inset-0 z-30 bg-black/50 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <div
        id={id}
        data-testid="session-sidebar"
        className={
          isOpen
            ? "absolute inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-border bg-surface md:static md:z-auto"
            : "w-64 border-r border-border bg-surface flex-col hidden md:flex"
        }
      >
        <div className="p-4 border-b border-border space-y-3">
          {isOpen && onClose && (
            <div className="flex items-center justify-between md:hidden">
              <span className="text-sm font-semibold text-foreground">Sessions</span>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close sessions"
                className="rounded-md p-1 text-muted transition-colors hover:bg-background hover:text-foreground"
              >
                <X size={16} aria-hidden />
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={() => void onCreateSession()}
            disabled={isCreating}
            aria-busy={isCreating}
            className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="text-lg leading-none">+</span>
            <span>{isCreating ? "Creating..." : "New Session"}</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.map((session) => {
            const isActive = session.id === activeSessionId;
            const isDeleting = deletingSessionId === session.id;
            return (
              <div
                key={session.id}
                className={`group flex items-center gap-1 rounded-md ${
                  isActive ? "bg-accent/10" : "hover:bg-surface"
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSwitchSession(session.id)}
                  aria-current={isActive ? "true" : undefined}
                  disabled={isDeleting}
                  title={session.displayLabel}
                  className={`min-w-0 flex-1 text-left px-3 py-2 text-sm transition-colors ${
                    isActive
                      ? "text-accent-text font-medium"
                      : "text-muted hover:text-foreground"
                  } disabled:opacity-60`}
                >
                  <span className="block truncate">{session.displayLabel}</span>
                  <span
                    className="block truncate text-xs font-normal opacity-70"
                    aria-hidden="true"
                  >
                    {session.id.substring(0, 8)}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => void onDeleteSession(session.id)}
                  disabled={isDeleting || deletingSessionId !== null}
                  aria-label={`Delete ${session.displayLabel}`}
                  className="mr-1 rounded-md p-1.5 text-muted opacity-100 md:opacity-0 transition hover:bg-background hover:text-red-400 group-hover:opacity-100 focus-visible:opacity-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Trash2 size={14} aria-hidden />
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

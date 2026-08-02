"use client";

import type { ChatSession } from "../../lib/hooks/useSessionManager";

type Props = {
  sessions: ChatSession[];
  activeSessionId: string;
  onCreateSession: () => void;
  onSwitchSession: (id: string) => void;
};

export default function SessionSidebar({
  sessions,
  activeSessionId,
  onCreateSession,
  onSwitchSession,
}: Props) {
  return (
    <div className="w-64 border-r border-border bg-surface flex-col hidden md:flex">
      <div className="p-4 border-b border-border">
        <button
          onClick={onCreateSession}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <span className="text-lg leading-none">+</span>
          <span>New Session</span>
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sessions.map((session) => (
          <button
            key={session.id}
            onClick={() => onSwitchSession(session.id)}
            className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors truncate ${
              session.id === activeSessionId
                ? "bg-accent/10 text-accent font-medium"
                : "text-muted hover:bg-surface hover:text-foreground"
            }`}
          >
            Session {session.id.substring(0, 8)}
          </button>
        ))}
      </div>
    </div>
  );
}

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  createSession as apiCreateSession,
  deleteSession as apiDeleteSession,
  listSessions,
  ChatError,
} from "../api";
import { cleanupSessionDocuments } from "../cleanupSessionDocuments";
import { getSessionId, setActiveSession } from "../session";

export type ChatSession = {
  id: string;
  createdAt: number;
  displayLabel: string;
};

const NEW_SESSION_LABEL = "New session";
const LEGACY_SESSIONS_KEY = "chatvector_sessions";
const LEGACY_ACTIVE_SESSION_KEY = "chatvector_active_session";

type ServerSession = {
  id: string;
  created_at: string;
  display_label?: string;
};

type LabelMeta = {
  serverLabel: string;
  fromQuestion: boolean;
};

function displayLabelFromPayload(value: unknown): string {
  return typeof value === "string" && value.length > 0 ? value : NEW_SESSION_LABEL;
}

function collapseQuestionLabel(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

function mapSession(session: ServerSession): ChatSession {
  return {
    id: session.id,
    createdAt: new Date(session.created_at).getTime(),
    displayLabel: displayLabelFromPayload(session.display_label),
  };
}

function removeLegacySessionListStorage(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(LEGACY_SESSIONS_KEY);
  localStorage.removeItem(LEGACY_ACTIVE_SESSION_KEY);
}

export function useSessionManager() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const labelMetaRef = useRef<Map<string, LabelMeta>>(new Map());
  const [isLoaded, setIsLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  const selectSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setActiveSession(id);
  }, []);

  const rememberServerSession = useCallback((session: ServerSession) => {
    labelMetaRef.current.set(session.id, {
      serverLabel: displayLabelFromPayload(session.display_label),
      fromQuestion: false,
    });
  }, []);

  const rememberServerSessions = useCallback(
    (serverSessions: ServerSession[]) => {
      const next = new Map<string, LabelMeta>();
      for (const session of serverSessions) {
        next.set(session.id, {
          serverLabel: displayLabelFromPayload(session.display_label),
          fromQuestion: false,
        });
      }
      labelMetaRef.current = next;
    },
    []
  );

  useEffect(() => {
    let cancelled = false;

    async function hydrate() {
      removeLegacySessionListStorage();

      try {
        let { sessions: backendSessions } = await listSessions();
        if (cancelled) return;

        if (backendSessions.length === 0) {
          const created = await apiCreateSession();
          if (cancelled) return;
          backendSessions = [created];
        }

        rememberServerSessions(backendSessions);
        const mapped = backendSessions.map(mapSession);
        setSessions(mapped);

        const storedId = getSessionId();
        const activeId =
          storedId && mapped.some((session) => session.id === storedId)
            ? storedId
            : mapped[0].id;
        selectSession(activeId);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        const message =
          err instanceof ChatError
            ? err.message
            : "Could not load sessions. Check your connection and try again.";
        setError(message);
      } finally {
        if (!cancelled) {
          setIsLoaded(true);
        }
      }
    }

    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [rememberServerSessions, selectSession]);

  const createNewSession = async () => {
    if (isCreating) return;
    setIsCreating(true);
    setError(null);
    try {
      const created = await apiCreateSession();
      rememberServerSession(created);
      const newSession = mapSession(created);
      setSessions((prev) => [newSession, ...prev]);
      selectSession(newSession.id);
    } catch (err) {
      const message =
        err instanceof ChatError
          ? err.message
          : "Could not create a new session. Please try again.";
      setError(message);
    } finally {
      setIsCreating(false);
    }
  };

  const switchSession = (id: string) => {
    if (sessions.some((session) => session.id === id)) {
      selectSession(id);
    }
  };

  const deleteSession = async (id: string) => {
    if (deletingSessionId || sessions.length === 0) return;
    setDeletingSessionId(id);
    setError(null);
    try {
      await cleanupSessionDocuments(id);
      await apiDeleteSession(id);

      const remaining = sessions.filter((session) => session.id !== id);
      if (remaining.length === 0) {
        const created = await apiCreateSession();
        rememberServerSession(created);
        const newSession = mapSession(created);
        setSessions([newSession]);
        selectSession(newSession.id);
        return;
      }

      setSessions(remaining);
      if (activeSessionId === id) {
        selectSession(remaining[0].id);
      }
    } catch (err) {
      const message =
        err instanceof ChatError
          ? err.message
          : "Could not delete the session. Please try again.";
      setError(message);
    } finally {
      setDeletingSessionId(null);
    }
  };

  const noteUserQuestion = useCallback((sessionId: string, text: string) => {
    const label = collapseQuestionLabel(text);
    if (!label) return;
    setSessions((prev) =>
      prev.map((session) => {
        if (session.id !== sessionId) return session;
        const meta = labelMetaRef.current.get(sessionId);
        if (meta?.fromQuestion) return session;
        labelMetaRef.current.set(sessionId, {
          serverLabel: meta?.serverLabel ?? session.displayLabel,
          fromQuestion: true,
        });
        return { ...session, displayLabel: label };
      })
    );
  }, []);

  const noteDocumentAttached = useCallback((sessionId: string, fileName: string) => {
    const name = fileName.trim();
    if (!name) return;
    setSessions((prev) =>
      prev.map((session) => {
        if (session.id !== sessionId) return session;
        const meta = labelMetaRef.current.get(sessionId);
        if (meta?.fromQuestion) return session;
        return { ...session, displayLabel: name };
      })
    );
  }, []);

  const noteSessionHistory = useCallback(
    (sessionId: string, hasUsefulUserQuestion: boolean) => {
      if (!hasUsefulUserQuestion) return;
      setSessions((prev) =>
        prev.map((session) => {
          if (session.id !== sessionId) return session;
          const meta = labelMetaRef.current.get(sessionId);
          if (!meta || meta.fromQuestion) return session;
          labelMetaRef.current.set(sessionId, { ...meta, fromQuestion: true });
          return { ...session, displayLabel: meta.serverLabel };
        })
      );
    },
    []
  );

  return {
    sessions,
    activeSessionId,
    createNewSession,
    switchSession,
    deleteSession,
    noteUserQuestion,
    noteDocumentAttached,
    noteSessionHistory,
    isLoaded,
    error,
    isCreating,
    deletingSessionId,
  };
}

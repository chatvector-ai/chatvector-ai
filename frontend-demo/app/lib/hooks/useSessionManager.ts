"use client";

import { useState, useEffect, useCallback } from "react";
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
};

const LEGACY_SESSIONS_KEY = "chatvector_sessions";
const LEGACY_ACTIVE_SESSION_KEY = "chatvector_active_session";

function mapSession(session: { id: string; created_at: string }): ChatSession {
  return {
    id: session.id,
    createdAt: new Date(session.created_at).getTime(),
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
  const [isLoaded, setIsLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  const selectSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setActiveSession(id);
  }, []);

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
  }, [selectSession]);

  const createNewSession = async () => {
    if (isCreating) return;
    setIsCreating(true);
    setError(null);
    try {
      const created = await apiCreateSession();
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

  return {
    sessions,
    activeSessionId,
    createNewSession,
    switchSession,
    deleteSession,
    isLoaded,
    error,
    isCreating,
    deletingSessionId,
  };
}

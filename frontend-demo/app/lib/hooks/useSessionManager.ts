"use client";

import { useState, useEffect } from "react";

export type ChatSession = {
  id: string;
  createdAt: number;
};

const SESSIONS_KEY = "chatvector_sessions";
const ACTIVE_SESSION_KEY = "chatvector_active_session";

function generateId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).substring(2, 15);
}

export function useSessionManager() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [isLoaded, setIsLoaded] = useState(false);

  useEffect(() => {
    // Load from localStorage on mount
    const storedSessionsStr = localStorage.getItem(SESSIONS_KEY);
    let loadedSessions: ChatSession[] = [];
    if (storedSessionsStr) {
      try {
        loadedSessions = JSON.parse(storedSessionsStr);
      } catch (e) {
        console.error("Failed to parse sessions", e);
      }
    }

    const storedActiveId = localStorage.getItem(ACTIVE_SESSION_KEY);

    if (loadedSessions.length === 0) {
      const newSession = { id: generateId(), createdAt: Date.now() };
      loadedSessions = [newSession];
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(loadedSessions));
      localStorage.setItem(ACTIVE_SESSION_KEY, newSession.id);
      setSessions(loadedSessions);
      setActiveSessionId(newSession.id);
    } else {
      setSessions(loadedSessions);
      if (storedActiveId && loadedSessions.some((s) => s.id === storedActiveId)) {
        setActiveSessionId(storedActiveId);
      } else {
        setActiveSessionId(loadedSessions[0].id);
        localStorage.setItem(ACTIVE_SESSION_KEY, loadedSessions[0].id);
      }
    }
    setIsLoaded(true);
  }, []);

  const createNewSession = () => {
    const newSession = { id: generateId(), createdAt: Date.now() };
    const newSessions = [newSession, ...sessions];
    setSessions(newSessions);
    setActiveSessionId(newSession.id);
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(newSessions));
    localStorage.setItem(ACTIVE_SESSION_KEY, newSession.id);
  };

  const switchSession = (id: string) => {
    if (sessions.some((s) => s.id === id)) {
      setActiveSessionId(id);
      localStorage.setItem(ACTIVE_SESSION_KEY, id);
    }
  };

  return {
    sessions,
    activeSessionId,
    createNewSession,
    switchSession,
    isLoaded,
  };
}

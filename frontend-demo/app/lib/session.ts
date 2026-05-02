const SESSION_STORAGE_KEY = "chatvector_session";
const SESSION_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

export type SessionData = {
  id: string;
  expiresAt: number;
};

function generateId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).substring(2, 15);
}

export function getSessionId(): string {
  if (typeof window === "undefined") {
    // Return a dummy ID during SSR; hydration will use the real one if needed,
    // but typically getSessionId is only called on user actions (like send).
    return "ssr-session";
  }

  const now = Date.now();
  const storedStr = localStorage.getItem(SESSION_STORAGE_KEY);

  if (storedStr) {
    try {
      const stored = JSON.parse(storedStr) as SessionData;
      if (stored.id && stored.expiresAt > now) {
        // Rolling expiry: bump the expiration time
        stored.expiresAt = now + SESSION_TTL_MS;
        localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(stored));
        return stored.id;
      }
    } catch (e) {
      console.warn("Failed to parse session data from localStorage", e);
    }
  }

  // Generate new session if missing, expired, or invalid
  const newSession: SessionData = {
    id: generateId(),
    expiresAt: now + SESSION_TTL_MS,
  };
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(newSession));
  return newSession.id;
}

export function resetSession(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  }
}

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

function saveSession(id: string): string {
  const now = Date.now();
  const session: SessionData = {
    id,
    expiresAt: now + SESSION_TTL_MS,
  };
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
  return id;
}

export function getSessionId(): string {
  if (typeof window === "undefined") {
    return "ssr-session";
  }

  const now = Date.now();
  const storedStr = localStorage.getItem(SESSION_STORAGE_KEY);

  if (storedStr) {
    try {
      const stored = JSON.parse(storedStr) as SessionData;
      if (stored.id && stored.expiresAt > now) {
        // Rolling expiry: bump the expiration time on access
        return saveSession(stored.id);
      }
    } catch (e) {
      console.warn("Failed to parse session data from localStorage", e);
    }
  }

  // Generate new session if missing, expired, or invalid
  return createNewSession();
}

export function createNewSession(): string {
  if (typeof window === "undefined") return "ssr-session";
  return saveSession(generateId());
}

export function resetSession(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(SESSION_STORAGE_KEY);
  }
}

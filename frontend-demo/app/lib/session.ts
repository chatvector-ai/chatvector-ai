const SESSION_STORAGE_KEY = "chatvector_session";
const SESSION_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

export type SessionData = {
  id: string;
  expiresAt: number;
};

export function generateId(): string {
  if (typeof crypto !== "undefined") {
    if (crypto.randomUUID) {
      return crypto.randomUUID();
    }
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
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

export function setActiveSession(id: string): void {
  if (typeof window !== "undefined") {
    saveSession(id);
  }
}

export function getSessionId(): string | null {
  if (typeof window === "undefined") {
    return null;
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

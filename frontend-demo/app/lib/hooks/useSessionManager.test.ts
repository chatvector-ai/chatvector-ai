import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useSessionManager } from "./useSessionManager";

const mockListSessions = vi.fn();
const mockCreateSession = vi.fn();
const mockDeleteSession = vi.fn();
const mockCleanupSessionDocuments = vi.fn();
const mockGetSessionId = vi.fn();
const mockSetActiveSession = vi.fn();

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    listSessions: (...args: unknown[]) => mockListSessions(...args),
    createSession: (...args: unknown[]) => mockCreateSession(...args),
    deleteSession: (...args: unknown[]) => mockDeleteSession(...args),
  };
});

vi.mock("../cleanupSessionDocuments", () => ({
  cleanupSessionDocuments: (...args: unknown[]) =>
    mockCleanupSessionDocuments(...args),
}));

vi.mock("../session", () => ({
  getSessionId: () => mockGetSessionId(),
  setActiveSession: (...args: unknown[]) => mockSetActiveSession(...args),
}));

describe("useSessionManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSessionId.mockReturnValue(null);
    mockCleanupSessionDocuments.mockResolvedValue(undefined);
    mockDeleteSession.mockResolvedValue(undefined);
  });

  it("keeps all 20 existing sessions and adds the 21st when createNewSession is called, and preserves all 21 across reload", async () => {
    const initialBackendSessions = Array.from({ length: 20 }, (_, index) => ({
      id: `session-${String(index + 1).padStart(2, "0")}`,
      created_at: new Date(1700000000000 + (20 - index) * 1000).toISOString(),
    }));
    const serverStore = [...initialBackendSessions];

    mockListSessions.mockImplementation(async () => ({
      sessions: [...serverStore],
    }));

    mockCreateSession.mockImplementation(async () => {
      const created = {
        id: "session-21-new",
        created_at: new Date(1700000100000).toISOString(),
      };
      serverStore.unshift(created);
      return created;
    });

    const { result, unmount } = renderHook(() => useSessionManager());

    await waitFor(() => {
      expect(result.current.isLoaded).toBe(true);
    });

    expect(result.current.sessions).toHaveLength(20);
    const previousIds = result.current.sessions.map((session) => session.id);

    await act(async () => {
      await result.current.createNewSession();
    });

    expect(result.current.sessions).toHaveLength(21);
    expect(result.current.sessions[0].id).toBe("session-21-new");
    expect(result.current.sessions.slice(1).map((session) => session.id)).toEqual(
      previousIds
    );
    expect(result.current.activeSessionId).toBe("session-21-new");

    unmount();

    const reloaded = renderHook(() => useSessionManager());
    await waitFor(() => {
      expect(reloaded.result.current.isLoaded).toBe(true);
    });

    expect(reloaded.result.current.sessions).toHaveLength(21);
    expect(reloaded.result.current.sessions.map((session) => session.id)).toEqual([
      "session-21-new",
      ...previousIds,
    ]);
  });

  it("shows New session until the first useful question, then keeps that label", async () => {
    mockListSessions.mockResolvedValue({
      sessions: [
        {
          id: "session-1",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    const { result, unmount } = renderHook(() => useSessionManager());
    await waitFor(() => expect(result.current.isLoaded).toBe(true));
    expect(result.current.sessions[0]?.displayLabel).toBe("New session");

    act(() => {
      result.current.noteDocumentAttached("session-1", "  notes.txt  ");
    });
    expect(result.current.sessions[0]?.displayLabel).toBe("notes.txt");

    act(() => {
      result.current.noteUserQuestion("session-1", "   \n\t  ");
    });
    expect(result.current.sessions[0]?.displayLabel).toBe("notes.txt");

    act(() => {
      result.current.noteUserQuestion("session-1", "Who\napproves   expenses?");
    });
    expect(result.current.sessions[0]?.displayLabel).toBe("Who approves expenses?");

    act(() => {
      result.current.noteUserQuestion("session-1", "What about travel?");
      result.current.noteDocumentAttached("session-1", "other.txt");
    });
    expect(result.current.sessions[0]?.displayLabel).toBe("Who approves expenses?");

    unmount();
    mockListSessions.mockResolvedValue({
      sessions: [
        {
          id: "session-1",
          created_at: "2026-01-01T00:00:00Z",
          display_label: "Who approves expenses?",
        },
      ],
    });
    const reloaded = renderHook(() => useSessionManager());
    await waitFor(() => expect(reloaded.result.current.isLoaded).toBe(true));
    expect(reloaded.result.current.sessions[0]?.displayLabel).toBe(
      "Who approves expenses?"
    );
  });
});

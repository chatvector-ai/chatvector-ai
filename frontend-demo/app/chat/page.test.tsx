import { useState, createRef } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatPage from "./page";
import type { AttachmentState } from "../lib/api";
import type { ChatSession } from "../lib/hooks/useSessionManager";
import type { RetrievalScope, RetrievalSettings } from "../lib/retrievalSettings";

const mockCreateNewSession = vi.fn();
const mockSwitchSession = vi.fn();
const mockDeleteSession = vi.fn();

let mockAttachment: AttachmentState | null = null;
let mockInitialScope: RetrievalScope = "session";
let mockSessions: ChatSession[] = [];
let mockActiveSessionId = "11111111-aaaa-bbbb-cccc-000000000001";

vi.mock("../lib/hooks/useSessionManager", () => ({
  useSessionManager: () => ({
    sessions: mockSessions,
    activeSessionId: mockActiveSessionId,
    createNewSession: mockCreateNewSession,
    switchSession: mockSwitchSession,
    deleteSession: mockDeleteSession,
    isLoaded: true,
    error: null,
    isCreating: false,
    deletingSessionId: null,
  }),
}));

vi.mock("../lib/hooks/useRetrievalSettings", () => ({
  useRetrievalSettings: () => {
    const [settings, setSettings] = useState<RetrievalSettings>({
      scope: mockInitialScope,
      matchCount: 5,
    });
    return {
      settings,
      setScope: (scope: RetrievalScope) =>
        setSettings((prev) => ({ ...prev, scope })),
      setMatchCount: (matchCount: number) =>
        setSettings((prev) => ({ ...prev, matchCount })),
      loaded: true,
    };
  },
}));

vi.mock("../lib/hooks/useChat", () => ({
  useChat: () => ({
    messages: [],
    historyLoading: false,
    input: "",
    setInput: vi.fn(),
    inflight: false,
    streaming: false,
    attachment: mockAttachment,
    sessionNotice: null,
    removeError: null,
    sendDisabled: true,
    bottomRef: createRef<HTMLDivElement>(),
    poll: {
      stage: undefined,
      completedStages: [],
      chunks: undefined,
      awaitingProcessing: false,
      queuePosition: undefined,
      processingTime: undefined,
      fileName: undefined,
      errorMessage: undefined,
      status: undefined,
    },
    handleSend: vi.fn(),
    handleKeyDown: vi.fn(),
    handleBeforeUpload: vi.fn(),
    handleUploadAccepted: vi.fn(),
    handleRemoveAttachment: vi.fn(),
    stopStreaming: vi.fn(),
  }),
}));

describe("ChatPage scope indicator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialScope = "session";
    mockActiveSessionId = "session-1";
    mockSessions = [{ id: "session-1", createdAt: 1, displayLabel: "New session" }];
    mockAttachment = {
      fileName: "notes.txt",
      documentId: "doc-1",
      statusEndpoint: "/documents/doc-1/status",
      status: "ready",
    };
  });

  it("shows the active scope with the selected document without opening developer settings, and updates when toggling tenant and session", async () => {
    const { container } = render(<ChatPage />);

    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");

    expect(
      screen.getByText("Session scope: searches only the selected document (notes.txt).")
    ).toBeVisible();

    await userEvent.click(screen.getByText("Retrieval settings"));
    await userEvent.click(screen.getByRole("radio", { name: "Tenant" }));

    expect(
      screen.getByText(
        "Tenant scope: searches the tenant's ready documents (can include documents other than the attached chip)."
      )
    ).toBeVisible();

    await userEvent.click(screen.getByRole("radio", { name: "Session" }));

    expect(
      screen.getByText("Session scope: searches only the selected document (notes.txt).")
    ).toBeVisible();
  });

  it("does not claim a document is searched when no document is attached in session scope", () => {
    mockAttachment = null;
    render(<ChatPage />);

    const indicator = screen.getByTestId("chat-scope-indicator");
    expect(indicator).toHaveTextContent(
      "Session scope: no document selected — upload a document to search it."
    );
  });
});

describe("ChatPage session navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialScope = "session";
    mockAttachment = null;
    mockActiveSessionId = "11111111-aaaa-bbbb-cccc-000000000001";
    mockSessions = [
      {
        id: "11111111-aaaa-bbbb-cccc-000000000001",
        createdAt: 2,
        displayLabel: "Who approves expenses?",
      },
      {
        id: "22222222-aaaa-bbbb-cccc-000000000002",
        createdAt: 1,
        displayLabel: "notes.txt",
      },
    ];
  });

  it("opens the session list via the narrow-screen control, anchors drawer and backdrop with absolute positioning inside the chat shell, triggers create/switch/delete, and closes cleanly", async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    const toggleButton = screen.getByRole("button", { name: /^Sessions$/i });
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");

    const sidebar = screen.getByTestId("session-sidebar");
    expect(sidebar.className).toContain("hidden");
    expect(sidebar.className).toContain("md:flex");

    await user.click(toggleButton);
    expect(toggleButton).toHaveAttribute("aria-expanded", "true");
    expect(sidebar.className).toContain("flex");
    expect(sidebar.className).toContain("absolute");
    expect(sidebar.className).not.toContain("fixed");
    expect(sidebar.className).not.toContain("hidden");

    const backdrop = screen.getByTestId("session-sidebar-backdrop");
    expect(backdrop.className).toContain("absolute");
    expect(backdrop.className).not.toContain("fixed");

    await user.click(screen.getByRole("button", { name: /New Session/i }));
    expect(mockCreateNewSession).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "notes.txt" }));
    expect(mockSwitchSession).toHaveBeenCalledWith(
      "22222222-aaaa-bbbb-cccc-000000000002"
    );

    await user.click(
      screen.getByRole("button", { name: "Delete notes.txt" })
    );
    expect(mockDeleteSession).toHaveBeenCalledWith(
      "22222222-aaaa-bbbb-cccc-000000000002"
    );

    await user.click(screen.getByRole("button", { name: /Close sessions/i }));
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");
    expect(sidebar.className).toContain("hidden");
    expect(
      screen.getByPlaceholderText(/Ask about your document/i)
    ).toBeInTheDocument();
  });

  it("keeps desktop sidebar actions directly available without opening the narrow-screen control", async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    const toggleButton = screen.getByRole("button", { name: /^Sessions$/i });
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");

    await user.click(screen.getByRole("button", { name: /New Session/i }));
    expect(mockCreateNewSession).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "notes.txt" }));
    expect(mockSwitchSession).toHaveBeenCalledWith(
      "22222222-aaaa-bbbb-cccc-000000000002"
    );

    await user.click(
      screen.getByRole("button", { name: "Delete Who approves expenses?" })
    );
    expect(mockDeleteSession).toHaveBeenCalledWith(
      "11111111-aaaa-bbbb-cccc-000000000001"
    );
  });
});

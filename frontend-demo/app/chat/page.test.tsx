import { useState, createRef } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatPage from "./page";
import {
  fetchRetrievalDiscovery,
  getSession,
  listDocuments,
  type AttachmentState,
} from "../lib/api";
import type { ChatSession } from "../lib/hooks/useSessionManager";
import type { AdvancedRetrievalState } from "../lib/advancedRetrieval";
import type { RetrievalScope } from "../lib/retrievalSettings";

const mockCreateNewSession = vi.fn();
const mockSwitchSession = vi.fn();
const mockDeleteSession = vi.fn();

let mockAttachment: AttachmentState | null = null;
let mockInitialScope: RetrievalScope | undefined = undefined;
let mockSessions: ChatSession[] = [];
let mockActiveSessionId = "11111111-aaaa-bbbb-cccc-000000000001";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    fetchRetrievalDiscovery: vi.fn().mockResolvedValue({
      presets: [],
      reranker_providers: ["similarity"],
    }),
    listDocuments: vi.fn().mockResolvedValue({ tenant_id: "t", documents: [] }),
    getSession: vi.fn().mockResolvedValue({
      id: "session-1",
      created_at: "2026-01-01T00:00:00Z",
      last_active: "2026-01-01T00:00:00Z",
      metadata: {},
      document_ids: [],
      display_label: "New session",
    }),
  };
});

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

vi.mock("../lib/hooks/useAdvancedRetrieval", () => ({
  useAdvancedRetrieval: () => {
    const [state, setState] = useState<AdvancedRetrievalState>({
      explicit: mockInitialScope ? { scope: mockInitialScope } : {},
    });
    return {
      state,
      loaded: true,
      setScope: (scope: RetrievalScope) =>
        setState({ explicit: { ...state.explicit, scope } }),
      setMatchCount: vi.fn(),
      setHybridEnabled: vi.fn(),
      setRerankingEnabled: vi.fn(),
      setRerankerProvider: vi.fn(),
      setQueryTransformationEnabled: vi.fn(),
      setQueryTransformationStrategy: vi.fn(),
      setHistoryAwareRetrieval: vi.fn(),
      setRetrievalHistoryWindow: vi.fn(),
      setGenerationHistoryWindow: vi.fn(),
      setMetadataFilter: vi.fn(),
      setPreset: (preset?: string) =>
        setState((prev) => {
          const explicit = { ...prev.explicit };
          const trimmed = preset?.trim();
          if (trimmed) {
            explicit.preset = trimmed;
          } else {
            delete explicit.preset;
          }
          return { explicit };
        }),
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

describe("ChatPage preset discovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAttachment = {
      fileName: "notes.txt",
      documentId: "doc-1",
      statusEndpoint: "/documents/doc-1/status",
      status: "ready",
    };
  });

  it("loads preset discovery when the advanced drawer opens", async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    expect(fetchRetrievalDiscovery).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("advanced-retrieval-open"));

    await waitFor(() => {
      expect(fetchRetrievalDiscovery).toHaveBeenCalledTimes(1);
    });
  });
});

describe("ChatPage metadata corpus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialScope = undefined;
    mockActiveSessionId = "session-1";
    mockSessions = [{ id: "session-1", createdAt: 1, displayLabel: "New session" }];
    mockAttachment = {
      fileName: "notes.txt",
      documentId: "doc-1",
      statusEndpoint: "/documents/doc-1/status",
      status: "ready",
    };
    vi.mocked(getSession).mockResolvedValue({
      id: "session-1",
      created_at: "2026-01-01T00:00:00Z",
      last_active: "2026-01-01T00:00:00Z",
      metadata: {},
      document_ids: ["doc-1", "doc-2"],
      display_label: "New session",
    });
    vi.mocked(listDocuments).mockResolvedValue({
      tenant_id: "t",
      documents: [
        {
          document_id: "doc-1",
          file_name: "notes.txt",
          status: "ready",
          created_at: null,
          updated_at: null,
          metadata: { department: "legal" },
        },
        {
          document_id: "doc-2",
          file_name: "other.txt",
          status: "ready",
          created_at: null,
          updated_at: null,
          metadata: { region: "us" },
        },
      ],
    });
  });

  it("uses metadata from every session document, not only the attachment", async () => {
    const user = userEvent.setup();
    render(<ChatPage />);

    await waitFor(() => {
      expect(getSession).toHaveBeenCalledWith("session-1");
    });

    await user.click(screen.getByTestId("advanced-retrieval-open"));

    await waitFor(() => {
      const keySelect = screen.getByTestId("metadata-filter-key");
      expect(keySelect).toContainHTML("department");
      expect(keySelect).toContainHTML("region");
    });
  });

  it("reloads document metadata when the attached document changes", async () => {
    const { rerender } = render(<ChatPage />);

    await waitFor(() => {
      expect(listDocuments).toHaveBeenCalledTimes(1);
    });

    mockAttachment = {
      fileName: "other.txt",
      documentId: "doc-2",
      statusEndpoint: "/documents/doc-2/status",
      status: "processing",
    };
    rerender(<ChatPage />);

    await waitFor(() => {
      expect(listDocuments).toHaveBeenCalledTimes(2);
    });
  });
});

describe("ChatPage scope indicator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialScope = undefined;
    mockActiveSessionId = "session-1";
    mockSessions = [{ id: "session-1", createdAt: 1, displayLabel: "New session" }];
    mockAttachment = {
      fileName: "notes.txt",
      documentId: "doc-1",
      statusEndpoint: "/documents/doc-1/status",
      status: "ready",
    };
  });

  it("shows session scope by default without opening advanced retrieval", () => {
    render(<ChatPage />);

    expect(screen.queryByTestId("advanced-retrieval-drawer")).not.toBeInTheDocument();
    expect(
      screen.getByText("Session scope: searches only the selected document (notes.txt).")
    ).toBeVisible();
    expect(screen.queryByText("Retrieval settings")).not.toBeInTheDocument();
  });

  it("updates the indicator after explicitly setting tenant scope in the drawer", async () => {
    render(<ChatPage />);

    await userEvent.click(screen.getByTestId("advanced-retrieval-open"));
    expect(screen.getByTestId("advanced-retrieval-drawer")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: /tenant/i }));

    expect(
      screen.getByText(
        "Tenant scope: searches the tenant's ready documents (can include documents other than the attached chip)."
      )
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

describe("ChatPage session document list", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialScope = undefined;
    mockActiveSessionId = "session-1";
    mockSessions = [{ id: "session-1", createdAt: 1, displayLabel: "New session" }];
    mockAttachment = {
      fileName: "notes.txt",
      documentId: "doc-1",
      statusEndpoint: "/documents/doc-1/status",
      status: "ready",
    };
    vi.mocked(getSession).mockResolvedValue({
      id: "session-1",
      created_at: "2026-01-01T00:00:00Z",
      last_active: "2026-01-01T00:00:00Z",
      metadata: {},
      document_ids: ["doc-1", "doc-2"],
      display_label: "New session",
    });
    vi.mocked(listDocuments).mockResolvedValue({
      tenant_id: "t",
      documents: [
        {
          document_id: "doc-1",
          file_name: "notes.txt",
          status: "completed",
          created_at: null,
          updated_at: null,
        },
        {
          document_id: "doc-2",
          file_name: "other.pdf",
          status: "failed",
          created_at: null,
          updated_at: null,
          error: { stage: "embedding", message: "boom" },
        },
      ],
    });
  });

  it("renders both session document names from one listDocuments response", async () => {
    render(<ChatPage />);

  await screen.findByTestId("session-document-list");
    expect(screen.getByTestId("document-list-row-doc-1")).toHaveTextContent(
      "notes.txt"
    );
    expect(screen.getByTestId("document-list-row-doc-2")).toHaveTextContent(
      "other.pdf"
    );
    await waitFor(() => {
      expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1);
    });
  });

  it("marks only the selected attachment in session scope", async () => {
    render(<ChatPage />);

    await screen.findByTestId("session-document-list");
    const inScope = screen.getAllByTestId("document-in-active-scope");
    expect(inScope).toHaveLength(1);
    expect(
      screen.getByTestId("document-list-row-doc-1").contains(inScope[0])
    ).toBe(true);
  });

  it("shows failure detail for failed session documents", async () => {
    render(<ChatPage />);

    const detail = await screen.findByTestId("document-failure-detail");
    expect(detail).toHaveTextContent("embedding: boom");
  });
});

describe("ChatPage session navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInitialScope = undefined;
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
      within(sidebar).getByRole("button", { name: "Delete notes.txt" })
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

  it("does not show batch-style configuration compare controls", () => {
    render(<ChatPage />);

    expect(screen.queryByRole("radio", { name: "Config compare" })).not.toBeInTheDocument();
    expect(screen.queryByText("Configuration A")).not.toBeInTheDocument();
    expect(screen.queryByText("Configuration B")).not.toBeInTheDocument();
  });
});

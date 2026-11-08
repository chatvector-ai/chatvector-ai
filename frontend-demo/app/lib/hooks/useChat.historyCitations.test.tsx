import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { useChat } from "./useChat";
import { EMPTY_ADVANCED_RETRIEVAL } from "../advancedRetrieval";
import MessageList from "../../components/chat/MessageList";

const mockGetSessionHistory = vi.fn();
const mockGetSession = vi.fn();
const mockGetDocumentStatus = vi.fn();

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    deleteDocument: vi.fn(),
    sendMessage: vi.fn(),
    sendMessageStream: vi.fn(),
    getSessionHistory: (...args: unknown[]) => mockGetSessionHistory(...args),
    getSession: (...args: unknown[]) => mockGetSession(...args),
    getDocumentStatus: (...args: unknown[]) => mockGetDocumentStatus(...args),
    DocumentNotFoundError: class DocumentNotFoundError extends Error {},
    ChatError: class ChatError extends Error {
      code = "unexpected";
    },
    StreamingDisabledError: class StreamingDisabledError extends Error {
      name = "StreamingDisabledError";
    },
  };
});

vi.mock("./useDocumentPolling", () => ({
  useDocumentPolling: () => ({
    status: "ready",
    stage: "completed",
    completedStages: [],
    chunks: undefined,
    awaitingProcessing: false,
    processingTime: undefined,
    errorMessage: undefined,
    queuePosition: undefined,
    fileName: undefined,
    apiStatus: undefined,
    statusDetail: undefined,
  }),
}));

vi.mock("../documentStore", () => ({
  saveUploadedDocument: vi.fn(),
  removeUploadedDocument: vi.fn(),
  getUploadedDocument: vi.fn(),
}));

const CITED_LINE = "handbook-v1.pdf · p.3-5 · chunk 2 · notes.txt · chunk 0";
// Long enough that the fake typewriter would still be running when the
// citation assertion fires. A restored row must show the finished answer.
const RESTORED_ANSWER = `Ten days. ${"policy ".repeat(80)}`;

function sessionPayload(sessionId: string, documentIds: string[] = []) {
  return {
    id: sessionId,
    created_at: "2026-01-01T00:00:00Z",
    last_active: "2026-01-01T00:00:00Z",
    metadata: {},
    document_ids: documentIds,
  };
}

function Transcript({ sessionId }: { sessionId: string }) {
  const chat = useChat(sessionId, EMPTY_ADVANCED_RETRIEVAL);
  return (
    <MessageList
      messages={chat.messages}
      inflight={chat.inflight}
      streaming={chat.streaming}
      historyLoading={chat.historyLoading}
      bottomRef={chat.bottomRef}
    />
  );
}

describe("restored history citations", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    mockGetSessionHistory.mockReset();
    mockGetSession.mockReset();
    mockGetDocumentStatus.mockReset();
    mockGetSession.mockImplementation(async (sessionId: string) =>
      sessionPayload(sessionId),
    );
  });

  it("renders the snapshot file and location line without a score", async () => {
    mockGetSessionHistory.mockResolvedValue({
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "What is the limit?",
          sources: [
            {
              file_name: "should-not-cite-user.pdf",
              page_number: 1,
              chunk_index: 0,
              score: 0.2,
            },
          ],
        },
        {
          id: "asst-1",
          role: "assistant",
          content: RESTORED_ANSWER,
          model: "gpt-test",
          latency_ms: 1200,
          chunks: 4,
          retrieval_debug: { original_query: "rewritten history query" },
          sources: [
            {
              file_name: "handbook-v1.pdf",
              page_number: 3,
              page_end: 5,
              chunk_index: 2,
              score: 0.91,
              score_type: "vector",
            },
            {
              file_name: "notes.txt",
              chunk_index: 0,
              score: 0.4,
            },
          ],
        },
      ],
    });
    mockGetSession.mockResolvedValue(sessionPayload("session-a", ["doc-1"]));
    mockGetDocumentStatus.mockResolvedValue({
      status: "completed",
      file_name: "handbook-v2.pdf",
    });

    render(<Transcript sessionId="session-a" />);

    expect(await screen.findByText(CITED_LINE)).toBeInTheDocument();
    expect(document.querySelector(".assistant-markdown p")?.textContent).toBe(
      RESTORED_ANSWER.trimEnd(),
    );
    await waitFor(() => expect(mockGetDocumentStatus).toHaveBeenCalled());

    expect(screen.getByText(CITED_LINE)).toBeInTheDocument();
    expect(screen.getByText("What is the limit?")).toBeInTheDocument();
    expect(screen.queryByText(/0\.91/)).not.toBeInTheDocument();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/handbook-v2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/should-not-cite-user/)).not.toBeInTheDocument();
    expect(screen.queryByText(/gpt-test/)).not.toBeInTheDocument();
    expect(screen.queryByText(/4 chunks/)).not.toBeInTheDocument();
    expect(screen.queryByText(/rewritten history query/)).not.toBeInTheDocument();
    expect(screen.queryByText(/1200/)).not.toBeInTheDocument();
  });

  it("renders no citation line for an empty, null, or missing snapshot", async () => {
    mockGetSessionHistory.mockResolvedValue({
      messages: [
        { id: "user-1", role: "user", content: "Earlier question" },
        { id: "asst-empty", role: "assistant", content: "Empty snapshot.", sources: [] },
        { id: "asst-null", role: "assistant", content: "Null snapshot.", sources: null },
        { id: "asst-missing", role: "assistant", content: "Missing snapshot." },
      ],
    });

    render(<Transcript sessionId="session-a" />);

    expect(await screen.findByText("Empty snapshot.")).toBeInTheDocument();
    expect(screen.getByText("Null snapshot.")).toBeInTheDocument();
    expect(screen.getByText("Missing snapshot.")).toBeInTheDocument();
    expect(screen.getByText("Earlier question")).toBeInTheDocument();
    expect(screen.queryByText(/chunk/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\.pdf/)).not.toBeInTheDocument();
  });

  it("replaces the citation line when the session switches", async () => {
    mockGetSessionHistory.mockImplementation(async (sessionId: string) => ({
      messages:
        sessionId === "session-b"
          ? [
              {
                id: "asst-b",
                role: "assistant",
                content: "See the notes.",
                sources: [{ file_name: "notes.txt", chunk_index: 4, score: 0.2 }],
              },
            ]
          : [
              {
                id: "asst-a",
                role: "assistant",
                content: "See the handbook.",
                sources: [
                  {
                    file_name: "handbook-v1.pdf",
                    page_number: 3,
                    chunk_index: 2,
                    score: 0.91,
                  },
                ],
              },
            ],
    }));

    const { rerender } = render(<Transcript sessionId="session-a" />);

    expect(
      await screen.findByText("handbook-v1.pdf · p.3 · chunk 2"),
    ).toBeInTheDocument();

    rerender(<Transcript sessionId="session-b" />);

    expect(await screen.findByText("notes.txt · chunk 4")).toBeInTheDocument();
    expect(screen.queryByText(/handbook-v1/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0\.91|0\.20|score/i)).not.toBeInTheDocument();
  });
});

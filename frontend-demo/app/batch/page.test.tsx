import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BatchPage from "./page";
import { BackendApiError } from "../lib/apiErrors";

vi.mock("../lib/hooks/useRetrievalSettings", () => ({
  useRetrievalSettings: () => ({
    settings: { scope: "session", matchCount: 5 },
    setMatchCount: vi.fn(),
    loaded: true,
  }),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    listDocuments: vi.fn(),
    sendBatchMessage: vi.fn(),
    sendSynthesizedBatchMessage: vi.fn(),
    sendConfigurationCompareBatchMessage: vi.fn(),
  };
});

import {
  listDocuments,
  sendBatchMessage,
  sendConfigurationCompareBatchMessage,
  type BatchChatResponse,
} from "../lib/api";

const DOCUMENTS = {
  tenant_id: "dev",
  documents: Array.from({ length: 3 }, (_, index) => ({
    document_id: `doc-${index + 1}`,
    file_name: `File ${index + 1}.pdf`,
    status: "completed",
    created_at: null,
    updated_at: null,
  })),
};

describe("BatchPage", () => {
  beforeEach(() => {
    vi.mocked(listDocuments).mockResolvedValue(DOCUMENTS);
    vi.mocked(sendBatchMessage).mockReset();
  });

  it("surfaces structured BackendApiError messages when document load fails", async () => {
    vi.mocked(listDocuments).mockRejectedValue(
      new BackendApiError(
        "Too many requests. Please slow down.",
        { code: "rate_limited", message: "Too many requests. Please slow down." },
        429,
      ),
    );

    render(<BatchPage />);

    expect(
      await screen.findByText("Too many requests. Please slow down."),
    ).toBeInTheDocument();
  });

  it("shows file type and failure detail in the batch document list", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      tenant_id: "dev",
      documents: [
        {
          document_id: "doc-1",
          file_name: "File 1.pdf",
          status: "failed",
          created_at: null,
          updated_at: null,
          error: { stage: "parse", message: "bad pdf" },
        },
      ],
    });

    render(<BatchPage />);

    expect(await screen.findByText("pdf")).toBeInTheDocument();
    expect(screen.getByTestId("document-failure-detail")).toHaveTextContent(
      "parse: bad pdf"
    );
  });

  it("shows document metadata in the batch document list", async () => {
    vi.mocked(listDocuments).mockResolvedValue({
      tenant_id: "dev",
      documents: [
        {
          document_id: "doc-1",
          file_name: "File 1.pdf",
          status: "completed",
          created_at: null,
          updated_at: null,
          metadata: { department: "legal" },
        },
        {
          document_id: "doc-2",
          file_name: "File 2.pdf",
          status: "completed",
          created_at: null,
          updated_at: null,
        },
      ],
    });

    render(<BatchPage />);

    expect(await screen.findByText("department=legal")).toBeInTheDocument();
    expect(screen.getByText("File 1.pdf")).toBeInTheDocument();
  });

  it("keeps compare results when mode changes during an in-flight request", async () => {
    let resolveBatch: ((value: BatchChatResponse) => void) | undefined;
    vi.mocked(sendBatchMessage).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveBatch = resolve;
        }) as ReturnType<typeof sendBatchMessage>,
    );

    render(<BatchPage />);
    await screen.findByText("File 1.pdf");

    const checkboxes = screen.getAllByRole("checkbox");
    for (const checkbox of checkboxes) {
      await userEvent.click(checkbox);
    }
    await userEvent.type(
      screen.getByRole("textbox", { name: "Question" }),
      "What changed?",
    );
    await userEvent.click(screen.getByRole("button", { name: "Run batch query" }));

    await userEvent.click(screen.getByRole("radio", { name: "Synthesize" }));

    resolveBatch?.({
      count: 3,
      success_count: 3,
      failure_count: 0,
      results: DOCUMENTS.documents.map((doc, index) => ({
        status: "ok",
        question: "What changed?",
        doc_ids: [doc.document_id],
        chunks: index + 1,
        answer: `Answer ${index + 1}`,
        sources: [],
        latency_ms: 100,
        model: "m",
      })),
    });

    await waitFor(() => {
      expect(screen.getByText("Answer 1")).toBeInTheDocument();
      expect(screen.getByText("Answer 2")).toBeInTheDocument();
      expect(screen.getByText("Answer 3")).toBeInTheDocument();
    });
  });

  it("ignores a second synchronous submit before React rerenders", async () => {
    let resolveBatch: ((value: BatchChatResponse) => void) | undefined;
    vi.mocked(sendBatchMessage).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveBatch = resolve;
        }) as ReturnType<typeof sendBatchMessage>,
    );

    render(<BatchPage />);
    await screen.findByText("File 1.pdf");

    await userEvent.click(screen.getAllByRole("checkbox")[0]!);
    await userEvent.type(
      screen.getByRole("textbox", { name: "Question" }),
      "What changed?",
    );

    const submitButton = screen.getByRole("button", { name: "Run batch query" });
    await userEvent.click(submitButton);
    await userEvent.click(submitButton);

    expect(sendBatchMessage).toHaveBeenCalledTimes(1);

    resolveBatch?.({
      count: 1,
      success_count: 1,
      failure_count: 0,
      results: [
        {
          status: "ok",
          question: "What changed?",
          doc_ids: ["doc-1"],
          chunks: 1,
          answer: "Answer 1",
          sources: [],
          latency_ms: 100,
          model: "m",
        },
      ],
    });

    await waitFor(() => {
      expect(screen.getByText("Answer 1")).toBeInTheDocument();
    });
  });

  it("runs configuration compare with debug_retrieval via two sparse configs", async () => {
    vi.mocked(sendConfigurationCompareBatchMessage).mockResolvedValue({
      count: 2,
      success_count: 2,
      failure_count: 0,
      results: [
        {
          status: "ok",
          question: "Hybrid?",
          doc_ids: ["doc-1"],
          answer: "Answer A",
          sources: [{ file_name: "a.pdf", score_type: "vector", score: 0.9 }],
          latency_ms: 120,
        },
        {
          status: "ok",
          question: "Hybrid?",
          doc_ids: ["doc-1"],
          answer: "Answer B",
          sources: [{ file_name: "a.pdf", score_type: "hybrid_rrf", score: 0.1 }],
          latency_ms: 140,
        },
      ],
    });

    render(<BatchPage />);
    await screen.findByText("File 1.pdf");

    await userEvent.click(screen.getByRole("radio", { name: "Config compare" }));
    await userEvent.click(screen.getAllByRole("checkbox")[0]!);
    await userEvent.type(
      screen.getByRole("textbox", { name: "Question" }),
      "Hybrid?",
    );

    const overrideLabels = screen.getAllByText("Override hybrid retrieval");
    await userEvent.click(overrideLabels[0]!);
    const hybridChecks = screen.getAllByRole("checkbox", { name: /Hybrid enabled/i });
    await userEvent.click(hybridChecks[0]!);

    await userEvent.click(overrideLabels[1]!);
    const matchCountOverrides = screen.getAllByText("Override match count");
    await userEvent.click(matchCountOverrides[1]!);

    await userEvent.click(
      screen.getByRole("button", { name: "Compare configurations" }),
    );

    expect(sendConfigurationCompareBatchMessage).toHaveBeenCalledTimes(1);
    expect(sendBatchMessage).not.toHaveBeenCalled();
    expect(await screen.findByText("Answer A")).toBeInTheDocument();
    expect(screen.getByText("Answer B")).toBeInTheDocument();
    expect(screen.getAllByText("Configuration A").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Configuration B").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });

  it("does not show chat session-scope indicator copy on the batch page", async () => {
    render(<BatchPage />);
    await screen.findByText("File 1.pdf");

    expect(screen.queryByTestId("chat-scope-indicator")).not.toBeInTheDocument();
    expect(screen.queryByText(/Session scope:/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Retrieval scope" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Batch mode help" }));
    expect(screen.getByText(/sends one query per document/i)).toBeInTheDocument();
    expect(screen.getByText(/sends one query across all selected documents/i)).toBeInTheDocument();
  });
});

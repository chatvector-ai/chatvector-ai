import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UploadModal from "./UploadModal";

vi.mock("../lib/api", () => ({
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
}));

import { uploadDocument, deleteDocument } from "../lib/api";

describe("UploadModal", () => {
  beforeEach(() => {
    vi.mocked(uploadDocument).mockReset();
    vi.mocked(deleteDocument).mockReset();
  });

  it("calls onClose when the close button is clicked", async () => {
    const onClose = vi.fn();
    render(
      <UploadModal
        onClose={onClose}
        onUploadAccepted={vi.fn()}
        attachment={null}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("lists all supported formats in the upload modal", () => {
    render(
      <UploadModal
        onClose={vi.fn()}
        onUploadAccepted={vi.fn()}
        attachment={null}
      />
    );

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput.accept).toBe(".pdf,.txt,.md,.markdown,.html,.htm,.docx");
    expect(screen.getByText("PDF, TXT, Markdown, HTML, and DOCX")).toBeInTheDocument();
    expect(screen.getByText("PDF · TXT · Markdown · HTML · DOCX")).toBeInTheDocument();
    expect(screen.queryByText("PDF or TXT")).not.toBeInTheDocument();
    expect(screen.queryByText("PDF · TXT")).not.toBeInTheDocument();
  });

  it("shows validation error when upload fails", async () => {
    vi.mocked(uploadDocument).mockRejectedValue(new Error("Only PDF files are supported"));

    render(
      <UploadModal
        onClose={vi.fn()}
        onUploadAccepted={vi.fn()}
        attachment={null}
      />
    );

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(await screen.findByText("Only PDF files are supported")).toBeInTheDocument();
  });

  it("accepts upload and notifies parent when upload succeeds", async () => {
    vi.mocked(uploadDocument).mockResolvedValue({
      documentId: "doc-123",
      statusEndpoint: "/documents/doc-123/status",
      queuePosition: 1,
    });
    const onUploadAccepted = vi.fn();

    render(
      <UploadModal
        onClose={vi.fn()}
        onUploadAccepted={onUploadAccepted}
        attachment={null}
      />
    );

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF"], "guide.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await screen.findByText("guide.pdf");
    expect(uploadDocument).toHaveBeenCalledWith(file, undefined);
    expect(deleteDocument).not.toHaveBeenCalled();
    expect(onUploadAccepted).toHaveBeenCalledWith({
      fileName: "guide.pdf",
      documentId: "doc-123",
      statusEndpoint: "/documents/doc-123/status",
      queuePosition: 1,
    });
  });

  it("passes replaceDocumentId to uploadDocument and keeps the same id when replacing a ready attachment", async () => {
    vi.mocked(uploadDocument).mockResolvedValue({
      documentId: "doc-old",
      statusEndpoint: "/documents/doc-old/status",
      queuePosition: 1,
    });
    const onUploadAccepted = vi.fn();

    render(
      <UploadModal
        onClose={vi.fn()}
        sessionId="sess-1"
        replaceDocumentId="doc-old"
        onUploadAccepted={onUploadAccepted}
        attachment={{ documentId: "doc-old", status: "ready" }}
      />
    );

    expect(screen.getByText(/Drop a file here/i)).toBeInTheDocument();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF"], "new-guide.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await screen.findByText("new-guide.pdf");
    expect(uploadDocument).toHaveBeenCalledWith(file, "sess-1", "doc-old");
    expect(deleteDocument).not.toHaveBeenCalled();
    expect(onUploadAccepted).toHaveBeenCalledWith({
      fileName: "new-guide.pdf",
      documentId: "doc-old",
      statusEndpoint: "/documents/doc-old/status",
      queuePosition: 1,
    });
  });

  it("leaves the prior attachment untouched when a replacement upload fails", async () => {
    vi.mocked(uploadDocument).mockRejectedValue(
      new Error("File exceeds the maximum size limit")
    );
    const onUploadAccepted = vi.fn();

    render(
      <UploadModal
        onClose={vi.fn()}
        sessionId="sess-1"
        replaceDocumentId="doc-old"
        onUploadAccepted={onUploadAccepted}
        attachment={{ documentId: "doc-old", status: "ready" }}
      />
    );

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF"], "too-large.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(
      await screen.findByText("File exceeds the maximum size limit")
    ).toBeInTheDocument();
    expect(uploadDocument).toHaveBeenCalledWith(file, "sess-1", "doc-old");
    expect(deleteDocument).not.toHaveBeenCalled();
    expect(onUploadAccepted).not.toHaveBeenCalled();
  });

  it("replaces a failed attachment in place and supports retrying after an initial HTTP error", async () => {
    vi.mocked(uploadDocument)
      .mockRejectedValueOnce(new Error("Temporary upload failure"))
      .mockResolvedValueOnce({
        documentId: "doc-failed",
        statusEndpoint: "/documents/doc-failed/status",
        queuePosition: 1,
      });
    const onUploadAccepted = vi.fn();

    render(
      <UploadModal
        onClose={vi.fn()}
        sessionId="sess-1"
        replaceDocumentId="doc-failed"
        onUploadAccepted={onUploadAccepted}
        attachment={{ documentId: "doc-failed", status: "failed" }}
      />
    );

    expect(screen.getByText(/Drop a file here/i)).toBeInTheDocument();

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF"], "fixed.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(
      await screen.findByText("Temporary upload failure")
    ).toBeInTheDocument();
    expect(deleteDocument).not.toHaveBeenCalled();
    expect(onUploadAccepted).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    await screen.findByText("fixed.pdf");
    expect(uploadDocument).toHaveBeenCalledTimes(2);
    expect(uploadDocument).toHaveBeenNthCalledWith(2, file, "sess-1", "doc-failed");
    expect(deleteDocument).not.toHaveBeenCalled();
    expect(onUploadAccepted).toHaveBeenCalledWith({
      fileName: "fixed.pdf",
      documentId: "doc-failed",
      statusEndpoint: "/documents/doc-failed/status",
      queuePosition: 1,
    });
  });

  it("surfaces server-side replacement failure when attachment status rolls back to ready with errorMessage", () => {
    const { rerender } = render(
      <UploadModal
        onClose={vi.fn()}
        sessionId="sess-1"
        replaceDocumentId="doc-old"
        onUploadAccepted={vi.fn()}
        attachment={{
          documentId: "doc-old",
          status: "processing",
          stage: "embedding",
        }}
      />
    );

    rerender(
      <UploadModal
        onClose={vi.fn()}
        sessionId="sess-1"
        replaceDocumentId="doc-old"
        onUploadAccepted={vi.fn()}
        attachment={{
          documentId: "doc-old",
          status: "ready",
          stage: "embedding",
          errorMessage: "Embedding provider exploded",
        }}
      />
    );

    expect(
      screen.getAllByText("Embedding provider exploded").length
    ).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText(/Upload Successful/i)).not.toBeInTheDocument();
  });
});

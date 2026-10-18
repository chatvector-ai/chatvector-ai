import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import UploadModal from "./UploadModal";

vi.mock("../lib/api", () => ({
  uploadDocument: vi.fn(),
}));

import { uploadDocument } from "../lib/api";

describe("UploadModal", () => {
  beforeEach(() => {
    vi.mocked(uploadDocument).mockReset();
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
    expect(onUploadAccepted).toHaveBeenCalledWith({
      fileName: "guide.pdf",
      documentId: "doc-123",
      statusEndpoint: "/documents/doc-123/status",
      queuePosition: 1,
    });
  });
});

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import ChatInput from "./ChatInput";

const mockPoll = {
  stage: undefined,
  completedStages: [] as string[],
  chunks: undefined,
  awaitingProcessing: false,
  queuePosition: undefined,
  processingTime: undefined,
  fileName: undefined,
  errorMessage: undefined,
  status: undefined,
  apiStatus: undefined,
  statusDetail: undefined,
};

function renderChatInput(overrides: Partial<ComponentProps<typeof ChatInput>> = {}) {
  const props: ComponentProps<typeof ChatInput> = {
    input: "",
    setInput: vi.fn(),
    sendDisabled: true,
    inflight: false,
    streaming: false,
    attachment: null,
    removeError: null,
    poll: mockPoll,
    handleSend: vi.fn(),
    handleKeyDown: vi.fn(),
    handleRemoveAttachment: vi.fn(),
    onUploadClick: vi.fn(),
    stopStreaming: vi.fn(),
    ...overrides,
  };

  return {
    ...render(<ChatInput {...props} />),
    props,
  };
}

describe("ChatInput", () => {
  it("mentions an active metadata filter in the scope indicator", () => {
    renderChatInput({ metadataFilterSummary: "department=legal" });
    expect(screen.getByTestId("chat-scope-indicator")).toHaveTextContent(
      "Metadata filter active: department=legal."
    );
  });

  it("shows preset scope copy when scope follows a selected preset", () => {
    renderChatInput({ scopeIndicator: { kind: "preset" } });
    expect(screen.getByTestId("chat-scope-indicator")).toHaveTextContent(
      "Scope follows the selected preset until you set scope explicitly."
    );
  });

  it("does not expose metadata filter controls in the composer", () => {
    renderChatInput({
      metadataFilterSummary: "department=legal",
    });
    expect(screen.queryByTestId("metadata-filter-key")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Key$/i)).not.toBeInTheDocument();
  });

  it("disables send when input is empty", () => {
    renderChatInput({ sendDisabled: true, input: "" });
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("shows typed markdown markers as plain text", () => {
    renderChatInput({ input: "See **bold** and _emphasis_" });
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
      "See **bold** and _emphasis_"
    );
  });

  it("enables send when input has text and send is allowed", () => {
    renderChatInput({ sendDisabled: false, input: "Hello" });
    expect(screen.getByRole("button", { name: "Send message" })).toBeEnabled();
  });

  it("disables textarea while a request is inflight", () => {
    renderChatInput({ inflight: true, input: "Hello", sendDisabled: true });
    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();
  });

  it("shows stop control while streaming instead of send", async () => {
    const stopStreaming = vi.fn();
    renderChatInput({
      streaming: true,
      input: "Hello",
      stopStreaming,
    });

    expect(screen.queryByRole("button", { name: "Send message" })).not.toBeInTheDocument();
    const stopButton = screen.getByRole("button", { name: "Stop generating" });
    await userEvent.click(stopButton);
    expect(stopStreaming).toHaveBeenCalledOnce();
  });

  it("disables send while attachment is processing", () => {
    renderChatInput({
      input: "Question?",
      sendDisabled: true,
      attachment: {
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
        status: "processing",
      },
    });

    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    expect(
      screen.getByText("Document still processing — sending is disabled until it is ready.")
    ).toBeInTheDocument();
  });

  it("explains a failed attachment before the user sends", () => {
    renderChatInput({
      input: "",
      sendDisabled: true,
      attachment: {
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
        status: "failed",
      },
    });

    expect(
      screen.getByText("Document processing failed. Please remove it and upload again.")
    ).toBeInTheDocument();
    expect(screen.getByText("guide.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove attachment" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
  });

  it("shows the selected document name for session scope when a document is attached", () => {
    renderChatInput({
      scopeIndicator: { kind: "default-session", fileName: "notes.txt" },
      attachment: {
        fileName: "notes.txt",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
        status: "ready",
      },
    });

    expect(
      screen.getByText("Session scope: searches only the selected document (notes.txt).")
    ).toBeInTheDocument();
  });

  it("does not claim a document is searched when session scope has no attachment", () => {
    renderChatInput({
      scopeIndicator: { kind: "default-session" },
      attachment: null,
    });

    expect(
      screen.getByText("Session scope: no document selected — upload a document to search it.")
    ).toBeInTheDocument();
  });

  it("shows ready-document tenant description when scope is tenant", () => {
    renderChatInput({
      scopeIndicator: { kind: "tenant" },
      attachment: {
        fileName: "notes.txt",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
        status: "ready",
      },
    });

    expect(
      screen.getByText(
        "Tenant scope: searches the tenant's ready documents (can include documents other than the attached chip)."
      )
    ).toBeInTheDocument();
  });

  it("disables UploadButton while attachment is processing and enables it when ready or failed", () => {
    const { rerender, props } = renderChatInput({
      attachment: {
        fileName: "guide.pdf",
        documentId: "doc-1",
        statusEndpoint: "/documents/doc-1/status",
        status: "processing",
      },
    });

    const uploadButton = screen.getByRole("button", { name: "Upload document" });
    expect(uploadButton).toBeDisabled();
    expect(uploadButton).toHaveAttribute(
      "title",
      "Wait for the current document to finish processing"
    );

    rerender(
      <ChatInput
        {...props}
        attachment={{
          fileName: "guide.pdf",
          documentId: "doc-1",
          statusEndpoint: "/documents/doc-1/status",
          status: "ready",
        }}
      />
    );
    expect(screen.getByRole("button", { name: "Upload document" })).toBeEnabled();

    rerender(
      <ChatInput
        {...props}
        attachment={{
          fileName: "guide.pdf",
          documentId: "doc-1",
          statusEndpoint: "/documents/doc-1/status",
          status: "failed",
        }}
      />
    );
    expect(screen.getByRole("button", { name: "Upload document" })).toBeEnabled();
  });
});

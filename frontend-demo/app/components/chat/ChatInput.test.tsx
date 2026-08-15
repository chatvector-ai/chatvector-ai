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
  errorMessage: undefined,
  status: undefined,
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
  it("disables send when input is empty", () => {
    renderChatInput({ sendDisabled: true, input: "" });
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
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
});

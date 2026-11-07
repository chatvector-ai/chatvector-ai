import { createRef } from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MessageList from "./MessageList";
import type { Message } from "../../lib/api";

const WELCOME_TEXT =
  "Hello! I'm ChatVector. Upload a document and I'll help you find answers from it.";
const ANSWER_TEXT = "Ten days.";

function renderList(
  messages: Message[],
  sessionId: string | null = "session-1",
) {
  const bottomRef = createRef<HTMLDivElement>();
  return render(
    <MessageList
      messages={messages}
      inflight={false}
      streaming={false}
      sessionId={sessionId}
      bottomRef={bottomRef}
    />,
  );
}

function requestBody(): Record<string, unknown> {
  const init = vi.mocked(globalThis.fetch).mock.calls[0]?.[1] as RequestInit;
  return JSON.parse(String(init.body)) as Record<string, unknown>;
}

describe("MessageList answer feedback", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("shows thumbs and a one-line comment only on an assistant bubble with a message id", () => {
    renderList([
      { id: 1, sender: "ai", text: WELCOME_TEXT },
      { id: 2, sender: "user", text: "What is the limit?", messageId: "user-1" },
      { id: 3, sender: "ai", text: "No stored id." },
      {
        id: 4,
        sender: "ai",
        text: "Still streaming",
        messageId: "asst-live",
        isStreaming: true,
      },
      { id: 5, sender: "ai", text: "Blank id", messageId: "   " },
      { id: 6, sender: "ai", text: ANSWER_TEXT, messageId: "asst-msg-9" },
    ]);

    expect(screen.getAllByRole("button", { name: "Thumbs up" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Thumbs down" })).toHaveLength(1);
    const comment = screen.getByRole("textbox", { name: "Optional comment" });
    expect(comment.tagName).toBe("INPUT");
    expect(comment).toHaveAttribute("type", "text");
    expect(screen.getByText(WELCOME_TEXT)).toBeInTheDocument();
    expect(screen.getByText("Still streaming")).toBeInTheDocument();
  });

  it("posts thumbs up with the session id and message id when the comment is empty", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({ id: "fb-1" }), { status: 201 }),
    );

    renderList([
      { id: 2, sender: "ai", text: ANSWER_TEXT, messageId: "asst-msg-9" },
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Thumbs up" }));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Saved");
    });

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    const url = String(vi.mocked(globalThis.fetch).mock.calls[0]?.[0]);
    expect(url.endsWith("/feedback")).toBe(true);
    expect(vi.mocked(globalThis.fetch).mock.calls[0]?.[1]).toEqual(
      expect.objectContaining({ method: "POST" }),
    );
    expect(requestBody()).toEqual({
      type: "answer",
      rating: 1,
      session_id: "session-1",
      message_id: "asst-msg-9",
    });
    expect(requestBody()).not.toHaveProperty("comment");
    expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Thumbs down" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByText(ANSWER_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Optional comment" })).toBeInTheDocument();
  });

  it("posts thumbs down with the one-line comment", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({ id: "fb-2" }), { status: 201 }),
    );

    renderList([
      { id: 2, sender: "ai", text: ANSWER_TEXT, messageId: "history-asst-1" },
    ]);

    await userEvent.type(
      screen.getByRole("textbox", { name: "Optional comment" }),
      "missed the page",
    );
    await userEvent.click(screen.getByRole("button", { name: "Thumbs down" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Thumbs down" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    expect(requestBody()).toEqual({
      type: "answer",
      rating: -1,
      session_id: "session-1",
      message_id: "history-asst-1",
      comment: "missed the page",
    });
    expect(screen.getByText(ANSWER_TEXT)).toBeInTheDocument();
    expect(String(vi.mocked(globalThis.fetch).mock.calls[0]?.[0])).not.toContain("/chat");
  });

  it("shows a 422 error and does not mark the rating saved", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "message_id_required" }), {
        status: 422,
      }),
    );

    renderList([
      { id: 2, sender: "ai", text: ANSWER_TEXT, messageId: "asst-msg-9" },
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Thumbs up" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("message_id_required");
    expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Thumbs down" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText(ANSWER_TEXT)).toBeInTheDocument();
  });

  it("shows a network error and does not mark the rating saved", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    renderList([
      { id: 2, sender: "ai", text: ANSWER_TEXT, messageId: "asst-msg-9" },
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Thumbs down" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot reach the server. Check your connection.",
    );
    expect(screen.getByRole("button", { name: "Thumbs down" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText(ANSWER_TEXT)).toBeInTheDocument();
  });

  it("does not post when the bubble has no session", async () => {
    renderList(
      [{ id: 2, sender: "ai", text: ANSWER_TEXT, messageId: "asst-msg-9" }],
      null,
    );

    await userEvent.click(screen.getByRole("button", { name: "Thumbs up" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This answer is not attached to a session.",
    );
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Thumbs up" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByText(ANSWER_TEXT)).toBeInTheDocument();
  });
});

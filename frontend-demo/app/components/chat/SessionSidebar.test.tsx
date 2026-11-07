import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SessionSidebar from "./SessionSidebar";
import type { ChatSession } from "../../lib/hooks/useSessionManager";

const sessions: ChatSession[] = [
  {
    id: "11111111-aaaa-bbbb-cccc-000000000001",
    createdAt: 2,
    displayLabel: "Who approves expenses?",
  },
  {
    id: "22222222-aaaa-bbbb-cccc-000000000002",
    createdAt: 1,
    displayLabel: "A".repeat(180),
  },
];

describe("SessionSidebar", () => {
  it("renders display_label as the row name and keeps the id as secondary text", () => {
    render(
      <SessionSidebar
        sessions={sessions}
        activeSessionId={sessions[0].id}
        onCreateSession={vi.fn()}
        onSwitchSession={vi.fn()}
        onDeleteSession={vi.fn()}
      />
    );

    const row = screen.getByRole("button", { name: "Who approves expenses?" });
    expect(row).toHaveAttribute("title", "Who approves expenses?");
    expect(row.querySelector("span")).toHaveClass("truncate");
    expect(screen.getByText("11111111")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Session 11111111" })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete Who approves expenses?" })
    ).toBeInTheDocument();

    const longLabel = "A".repeat(180);
    const longRow = screen.getByRole("button", { name: longLabel });
    expect(longRow).toHaveAttribute("title", longLabel);
    expect(longRow.querySelector("span")).toHaveClass("truncate");
    expect(
      screen.queryByRole("button", { name: "Session 22222222" })
    ).not.toBeInTheDocument();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children?: string }) => {
    if (children?.includes("THROW")) {
      throw new Error("parse failed");
    }
    return <p>{children}</p>;
  },
}));

import AiResponseContent from "./AiResponseContent";

describe("AiResponseContent markdown fallback", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a failed chunk as text and renders once the text changes", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender, container } = render(
      <AiResponseContent text="THROW **bol" isStreaming detailsVisible={false} />
    );

    expect(container.textContent).toContain("THROW **bol");
    expect(container.querySelector("p")).toBeNull();
    expect(container.querySelector("span.bg-accent")).not.toBeNull();

    rerender(<AiResponseContent text="**bold**" isStreaming={false} />);

    expect(container.querySelector("p")?.textContent).toBe("**bold**");
    expect(container.textContent).not.toContain("THROW");
    expect(container.querySelector("span.bg-accent")).toBeNull();
  });
});

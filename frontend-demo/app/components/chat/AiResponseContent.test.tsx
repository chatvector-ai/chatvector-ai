import { createRef } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AiResponseContent from "./AiResponseContent";
import MessageList from "./MessageList";

function executableMarkup(container: HTMLElement) {
  const live: string[] = [];
  if (container.querySelector("script, iframe, object, embed, style, img")) {
    live.push(container.querySelector("script, iframe, object, embed, style, img")!.tagName);
  }
  for (const el of container.querySelectorAll("*")) {
    for (const name of el.getAttributeNames()) {
      if (name.toLowerCase().startsWith("on")) live.push(name);
      if (name === "href" && (el.getAttribute(name) ?? "").toLowerCase().includes("javascript:")) {
        live.push(el.getAttribute(name) ?? "");
      }
    }
  }
  return live;
}

describe("AiResponseContent", () => {
  it("renders file and chunk on the visible citation line without score or confidence while inspector is closed", () => {
    render(
      <AiResponseContent
        text="Here is the live answer."
        sources={[
          {
            file_name: "notes.txt",
            chunk_index: 0,
            score: 0.63,
            score_type: "vector",
          },
        ]}
      />
    );

    expect(screen.getByText("notes.txt · chunk 0")).toBeInTheDocument();
    expect(screen.queryByText(/0\.63/)).not.toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });

  it("shows score details when the retrieval inspector is opened", async () => {
    const user = userEvent.setup();
    render(
      <AiResponseContent
        text="Here is the live answer."
        sources={[
          {
            file_name: "notes.txt",
            chunk_index: 0,
            score: 0.63,
            score_type: "vector",
          },
        ]}
      />
    );

    await user.click(screen.getByText("Retrieval inspector"));

    expect(screen.getByText("0.63")).toBeInTheDocument();
    expect(screen.getByText("vector")).toBeInTheDocument();
  });

  it("includes page number when present and deduplicates repeated sources", () => {
    render(
      <AiResponseContent
        text="Summary from PDF."
        sources={[
          { file_name: "manual.pdf", page_number: 3, chunk_index: 1, score: 0.81 },
          { file_name: "manual.pdf", page_number: 3, chunk_index: 1, score: 0.81 },
        ]}
      />
    );

    expect(screen.getByText("manual.pdf · p.3 · chunk 1")).toBeInTheDocument();
    expect(screen.queryByText(/0\.81/)).not.toBeInTheDocument();
  });

  it("renders no citation line when sources are empty or missing, or while streaming", () => {
    const { rerender } = render(
      <AiResponseContent text="General answer without sources." sources={[]} />
    );

    expect(screen.queryByText(/chunk/i)).not.toBeInTheDocument();

    rerender(<AiResponseContent text="General answer without sources." />);
    expect(screen.queryByText(/chunk/i)).not.toBeInTheDocument();

    rerender(
      <AiResponseContent
        text="Partial token..."
        isStreaming={true}
        detailsVisible={false}
        sources={[{ file_name: "notes.txt", chunk_index: 0, score: 0.63 }]}
      />
    );
    expect(screen.queryByText(/notes\.txt/)).not.toBeInTheDocument();
  });

  it("renders emphasis without showing the marker characters", () => {
    const { container } = render(
      <AiResponseContent text="This is **bold** and _emphasis_." />
    );

    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("em")?.textContent).toBe("emphasis");
    expect(container.textContent).not.toContain("**");
    expect(container.textContent).not.toContain("_emphasis_");
  });

  it("renders a list and a fenced code block", () => {
    const { container } = render(
      <AiResponseContent
        text={["- alpha", "- beta", "", "```", "const x = 1", "```"].join("\n")}
      />
    );

    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "alpha",
      "beta",
    ]);
    const code = container.querySelector("pre code");
    expect(code).not.toBeNull();
    expect(code?.textContent).toContain("const x = 1");
    expect(container.textContent).not.toContain("```");
  });

  it("renders a markdown table", () => {
    render(
      <AiResponseContent
        text={["| A | B |", "| --- | --- |", "| 1 | 2 |"].join("\n")}
      />
    );

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "A" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "2" })).toBeInTheDocument();
  });

  it("does not insert model HTML as an executable element", () => {
    const { container } = render(
      <AiResponseContent
        text={[
          "Hello **there**",
          "",
          '<script>alert(1)</script>',
          '<img src="x" onerror="alert(1)">',
          '[click](javascript:alert(1))',
        ].join("\n\n")}
      />
    );

    expect(executableMarkup(container)).toEqual([]);
    expect(container.querySelector("strong")?.textContent).toBe("there");
    expect(container.innerHTML.toLowerCase()).not.toContain("<script");
    expect(container.innerHTML.toLowerCase()).not.toContain("onerror");
  });

  it("keeps the streaming cursor and renders markdown once the answer finishes", () => {
    const { rerender, container } = render(
      <AiResponseContent text="**bol" isStreaming detailsVisible={false} />
    );

    expect(container.querySelector("span.bg-accent")).not.toBeNull();
    expect(container.textContent).toContain("bol");

    rerender(<AiResponseContent text="**bold** item" isStreaming={false} />);

    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.textContent).not.toContain("**");
    expect(container.querySelector("span.bg-accent")).toBeNull();
  });

  it("shows markdown markers literally in a user message", () => {
    const bottomRef = createRef<HTMLDivElement>();

    render(
      <MessageList
        messages={[
          { id: 2, sender: "user", text: "See **bold**" },
          { id: 3, sender: "ai", text: "Use **bold**", isStreaming: false },
        ]}
        inflight={false}
        streaming={false}
        bottomRef={bottomRef}
      />
    );

    expect(screen.getByText("See **bold**")).toBeInTheDocument();
    expect(screen.getByText("See **bold**").className).toContain("whitespace-pre-wrap");
    const strong = screen.getByText("bold");
    expect(strong.tagName).toBe("STRONG");
    expect(strong.closest(".assistant-markdown")?.className).not.toContain(
      "whitespace-pre-wrap"
    );
    expect(strong.closest(".assistant-markdown")?.parentElement?.className).not.toContain(
      "whitespace-pre-wrap"
    );
    expect(screen.queryByText("Use **bold**")).not.toBeInTheDocument();
  });
});

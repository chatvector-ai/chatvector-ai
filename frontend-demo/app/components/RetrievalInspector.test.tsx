import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RetrievalInspector from "./RetrievalInspector";

async function openInspector() {
  const user = userEvent.setup();
  await user.click(screen.getByText("Retrieval inspector"));
}

describe("RetrievalInspector query section", () => {
  it("renders skipped state and reason when resolution was not applied", async () => {
    render(
      <RetrievalInspector
        data={{
          question: "what about renewal?",
          retrieval_debug: {
            history_resolution_applied: false,
            history_resolution_skipped_reason: "standalone_question",
          },
        }}
      />
    );

    expect(screen.getByText("(developer)")).toBeInTheDocument();
    expect(screen.queryByText("Skipped (standalone_question)")).not.toBeInTheDocument();

    await openInspector();

    expect(screen.getByText("Skipped (standalone_question)")).toBeInTheDocument();
    expect(screen.queryByText("Ran")).not.toBeInTheDocument();
    expect(screen.getByText("what about renewal?")).toBeInTheDocument();
  });

  it("renders fallback state separately from skip", async () => {
    render(
      <RetrievalInspector
        data={{
          question: "follow-up",
          retrieval_debug: {
            history_resolution_fallback_reason: "llm_failure",
            effective_retrieval_query: "follow-up",
          },
        }}
      />
    );

    await openInspector();

    expect(screen.getByText("Fallback (llm_failure)")).toBeInTheDocument();
    expect(screen.queryByText(/Skipped/)).not.toBeInTheDocument();
  });

  it("renders ran state without inventing a resolved query when omitted", async () => {
    render(
      <RetrievalInspector
        data={{
          question: "unchanged wording",
          retrieval_debug: {
            history_resolution_applied: true,
            effective_retrieval_query: "unchanged wording",
          },
        }}
      />
    );

    await openInspector();

    expect(screen.getByText("Ran")).toBeInTheDocument();
    expect(screen.queryByText("Resolved query")).not.toBeInTheDocument();
    expect(screen.getAllByText("unchanged wording").length).toBe(2);
  });

  it("renders resolved and searched queries when present", async () => {
    render(
      <RetrievalInspector
        data={{
          question: "what about renewal?",
          retrieval_debug: {
            history_resolution_applied: true,
            history_resolved_query: "What is the renewal policy for POL-HR-014?",
            effective_retrieval_query: "What is the renewal policy for POL-HR-014?",
          },
        }}
      />
    );

    await openInspector();

    expect(screen.getByText("Resolved query")).toBeInTheDocument();
    expect(screen.getByText("Searched query")).toBeInTheDocument();
    expect(
      screen.getAllByText("What is the renewal policy for POL-HR-014?").length
    ).toBe(2);
  });

  it("does not render transformed queries when the list is empty or missing", async () => {
    render(
      <RetrievalInspector
        data={{
          question: "plain question",
          retrieval_debug: {
            transformed_queries: [],
          },
        }}
      />
    );

    await openInspector();

    expect(screen.queryByText("Transformed queries")).not.toBeInTheDocument();
  });

  it("keeps the inspector inside a collapsed details element", () => {
    const { container } = render(
      <RetrievalInspector
        data={{
          question: "Q",
          retrieval_debug: { effective_retrieval_query: "Q" },
        }}
      />
    );

    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details?.hasAttribute("open")).toBe(false);
    expect(screen.getByText("Retrieval inspector")).toBeInTheDocument();
    expect(screen.getByText("(developer)")).toBeInTheDocument();
  });

  it("omits history rows when history fields are absent", async () => {
    render(
      <RetrievalInspector
        data={{
          question: "only original",
        }}
      />
    );

    await openInspector();

    expect(screen.getByText("only original")).toBeInTheDocument();
    expect(screen.queryByText(/Skipped/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Fallback/)).not.toBeInTheDocument();
    expect(screen.queryByText("Ran")).not.toBeInTheDocument();
  });
});

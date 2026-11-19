import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BatchResultCard, hasPartialBatchResult } from "./BatchResultCard";
import type { BatchResultItem } from "../../lib/api";

describe("BatchResultCard helpers", () => {
  it("treats partial error payloads with answer or sources as renderable", () => {
    const partial: BatchResultItem = {
      status: "error",
      question: "Q?",
      doc_ids: ["doc-1"],
      chunks: 1,
      answer: "Partial answer.",
      sources: [{ file_name: "a.pdf", page_number: 1, chunk_index: 0, score: 0.5 }],
      latency_ms: 100,
      model: "m",
      error: { code: "llm_rate_limited", message: "Slow down." },
    };
    expect(hasPartialBatchResult(partial)).toBe(true);
  });

  it("treats error-only payloads without partial content as non-renderable body", () => {
    const errorOnly: BatchResultItem = {
      status: "error",
      question: "Q?",
      doc_ids: ["doc-1"],
      error: { code: "query_processing_failed", message: "Failed." },
    };
    expect(hasPartialBatchResult(errorOnly)).toBe(false);
  });

  it("renders the answer through the assistant markdown path", () => {
    render(
      <BatchResultCard
        title="Notes"
        result={{
          status: "ok",
          question: "Q?",
          doc_ids: ["doc-1"],
          answer: "Use **bold**.",
          sources: [],
          chunks: 1,
          model: "m",
          latency_ms: 10,
        }}
      />
    );

    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.queryByText(/\*\*bold\*\*/)).not.toBeInTheDocument();
  });

  it("renders single labeled score rows and scale note in inspector for hybrid result", async () => {
    const user = userEvent.setup();
    const hybridResult: BatchResultItem = {
      status: "ok",
      question: "What is the policy?",
      doc_ids: ["doc-1"],
      answer: "The policy allows hybrid work.",
      sources: [
        {
          file_name: "policy.pdf",
          page_number: 2,
          chunk_index: 1,
          score: 0.02,
          score_type: "hybrid_rrf",
          rrf_score: 0.02,
          vector_score: 0.72,
        },
      ],
      chunks: 1,
      model: "chat-model",
    };

    render(<BatchResultCard title="Configuration B" result={hybridResult} />);

    await user.click(screen.getByText("Retrieval inspector"));

    expect(screen.getAllByText("Rank score")).toHaveLength(1);
    expect(screen.getAllByText("Vector similarity")).toHaveLength(1);
    expect(screen.queryByText("Hybrid RRF score")).not.toBeInTheDocument();
    expect(screen.queryByText("RRF score")).not.toBeInTheDocument();
    expect(screen.queryByText("Vector similarity score")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Rank score and vector similarity use different scales and are not directly comparable.",
      ),
    ).toBeInTheDocument();
  });
});

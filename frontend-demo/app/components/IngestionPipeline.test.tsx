import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import IngestionPipeline from "./IngestionPipeline";
import {
  PIPELINE_STAGES,
  PIPELINE_STAGE_LABELS,
  STAGE_LABELS,
} from "../lib/stageLabels";

describe("IngestionPipeline", () => {
  it("includes retrying in STAGE_LABELS, PIPELINE_STAGES, and PIPELINE_STAGE_LABELS", () => {
    expect(STAGE_LABELS.retrying).toBe("Retrying");
    expect(PIPELINE_STAGES).toContain("retrying");
    expect(PIPELINE_STAGE_LABELS.retrying).toBe("Retrying");
  });

  it("renders the retrying state with a distinct amber indicator instead of resetting to pending", () => {
    render(<IngestionPipeline currentStage="retrying" />);

    const retryingLabel = screen.getByText("Retrying");
    expect(retryingLabel).toBeInTheDocument();
    expect(retryingLabel.className).toContain("text-amber-400");

    const retryingRow = retryingLabel.closest("li");
    expect(retryingRow).toHaveAttribute("data-stage", "retrying");
    expect(retryingRow).toHaveAttribute("data-state", "retrying");

    const uploadingRow = screen.getByText("Uploading").closest("li");
    const queuedRow = screen.getByText("Queued").closest("li");
    expect(uploadingRow).toHaveAttribute("data-state", "completed");
    expect(queuedRow).toHaveAttribute("data-state", "completed");
  });

  it("transitions cleanly from a later stage into retrying and back without freezing", () => {
    const { rerender } = render(
      <IngestionPipeline
        currentStage="embedding"
        chunks={{ total: 10, processed: 4 }}
      />
    );

    rerender(
      <IngestionPipeline
        currentStage="retrying"
        chunks={{ total: 10, processed: 4 }}
      />
    );

    const retryingRow = screen.getByText("Retrying").closest("li");
    expect(retryingRow).toHaveAttribute("data-state", "retrying");

    rerender(
      <IngestionPipeline
        currentStage="embedding"
        chunks={{ total: 10, processed: 10 }}
      />
    );

    const embeddingRow = screen.getByText("Embedding").closest("li");
    expect(embeddingRow).toHaveAttribute("data-state", "active");
    expect(screen.queryByText("Retrying")).not.toBeInTheDocument();
  });
});

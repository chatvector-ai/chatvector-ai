import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import IngestionPipeline from "./IngestionPipeline";
import AttachmentChip from "./AttachmentChip";

describe("IngestionPipeline", () => {
  it("renders retrying in place of the in-progress stage without marking storing completed", () => {
    const { container, rerender } = render(
      <IngestionPipeline currentStage="uploading" />
    );

    const uploadingRow = container.querySelector('[data-stage="uploading"]');
    expect(uploadingRow).toHaveAttribute("data-stage-state", "active");
    expect(container.querySelector('[data-stage="retrying"]')).toBeNull();

    rerender(<IngestionPipeline currentStage="retrying" />);

    const retryingRow = container.querySelector('[data-stage="retrying"]');
    const storingRow = container.querySelector('[data-stage="storing"]');
    const completedRow = container.querySelector('[data-stage="completed"]');

    expect(screen.getByText("Retrying")).toBeInTheDocument();
    expect(retryingRow).toHaveAttribute("data-stage-state", "retrying");
    expect(container.querySelector('[data-stage="uploading"]')).toBeNull();
    expect(storingRow).toHaveAttribute("data-stage-state", "pending");
    expect(completedRow).toHaveAttribute("data-stage-state", "pending");
    expect(container.querySelector('[data-stage-state="failed"]')).toBeNull();
  });

  it("transitions from retrying to failed on an earlier stage when retries are exhausted", () => {
    const { container, rerender } = render(
      <IngestionPipeline currentStage="retrying" />
    );

    expect(
      container.querySelector('[data-stage="retrying"]')
    ).toHaveAttribute("data-stage-state", "retrying");

    rerender(
      <IngestionPipeline
        currentStage="embedding"
        failed
        errorMessage="Embedding service unavailable"
      />
    );

    const embeddingRow = container.querySelector('[data-stage="embedding"]');
    const retryingRow = container.querySelector('[data-stage="retrying"]');

    expect(embeddingRow).toHaveAttribute("data-stage-state", "failed");
    expect(retryingRow).toBeNull();
    expect(
      screen.getByText("Embedding service unavailable")
    ).toBeInTheDocument();
  });

  it("renders ordinary in-progress stages and completed state without a pending retrying row", () => {
    const { container, rerender } = render(
      <IngestionPipeline currentStage="uploading" />
    );

    expect(
      container.querySelector('[data-stage="uploading"]')
    ).toHaveAttribute("data-stage-state", "active");
    expect(container.querySelector('[data-stage="retrying"]')).toBeNull();

    rerender(<IngestionPipeline currentStage="retrying" />);
    expect(
      container.querySelector('[data-stage="retrying"]')
    ).toHaveAttribute("data-stage-state", "retrying");

    rerender(<IngestionPipeline currentStage="completed" />);

    expect(
      container.querySelector('[data-stage="completed"]')
    ).toHaveAttribute("data-stage-state", "completed");
    expect(
      container.querySelector('[data-stage="storing"]')
    ).toHaveAttribute("data-stage-state", "completed");
    expect(container.querySelector('[data-stage="retrying"]')).toBeNull();
  });
});

describe("AttachmentChip retrying state", () => {
  it("shows Retrying while status is processing and the file name when terminal", () => {
    const { rerender } = render(
      <AttachmentChip
        fileName="report.pdf"
        status="processing"
        stage="retrying"
        onRemove={vi.fn()}
      />
    );

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("Retrying")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();

    rerender(
      <AttachmentChip
        fileName="report.pdf"
        status="failed"
        stage="embedding"
        onRemove={vi.fn()}
      />
    );

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.queryByText("Retrying")).not.toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });

  it("keeps notes.txt visible for processing, ready, and failed chips", () => {
    const { rerender } = render(
      <AttachmentChip
        fileName="notes.txt"
        status="processing"
        stage="embedding"
        chunks={{ total: 3, processed: 1 }}
        onRemove={vi.fn()}
      />
    );

    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    expect(screen.getByText("Embedding (3 chunks)")).toBeInTheDocument();

    rerender(
      <AttachmentChip fileName="notes.txt" status="ready" onRemove={vi.fn()} />
    );
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();

    rerender(
      <AttachmentChip fileName="notes.txt" status="failed" onRemove={vi.fn()} />
    );
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    expect(screen.queryByText("Failed")).not.toBeInTheDocument();
  });
});

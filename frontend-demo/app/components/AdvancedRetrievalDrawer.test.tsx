import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AdvancedRetrievalDrawer from "./AdvancedRetrievalDrawer";

const baseProps = {
  open: false,
  onOpenChange: vi.fn(),
  state: { explicit: {} as const },
  onScopeChange: vi.fn(),
  onMatchCountChange: vi.fn(),
  onHybridEnabledChange: vi.fn(),
  onRerankingEnabledChange: vi.fn(),
  onRerankerProviderChange: vi.fn(),
  onQueryTransformationEnabledChange: vi.fn(),
  onQueryTransformationStrategyChange: vi.fn(),
  onHistoryAwareRetrievalChange: vi.fn(),
  onRetrievalHistoryWindowChange: vi.fn(),
  onGenerationHistoryWindowChange: vi.fn(),
  availableRerankerProviders: ["similarity"] as const,
};

describe("AdvancedRetrievalDrawer", () => {
  it("does not list cohere without discovery", async () => {
    render(
      <AdvancedRetrievalDrawer {...baseProps} open onOpenChange={vi.fn()} />
    );

    expect(screen.queryByRole("radio", { name: /cohere/i })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /similarity/i })).toBeInTheDocument();
  });

  it("lists cohere when discovery includes it", () => {
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        availableRerankerProviders={["similarity", "cohere"]}
      />
    );

    expect(screen.getByRole("radio", { name: /cohere/i })).toBeInTheDocument();
  });

  it("has no persona, provider, chunk, or graph controls", () => {
    render(<AdvancedRetrievalDrawer {...baseProps} open />);

    expect(screen.queryByText(/persona/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/llm provider/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/chunk strategy/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/graphrag/i)).not.toBeInTheDocument();
  });

  it("marks hybrid explicit when toggled", async () => {
    const onHybrid = vi.fn();
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        onHybridEnabledChange={onHybrid}
      />
    );

    await userEvent.click(screen.getByRole("checkbox", { name: /hybrid search/i }));
    expect(onHybrid).toHaveBeenCalledWith(true);
  });
});

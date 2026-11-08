import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AdvancedRetrievalState, RerankerProvider } from "../lib/advancedRetrieval";
import type { DocumentScalarMetadata } from "../lib/documentMetadata";
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
  onMetadataFilterChange: vi.fn(),
  metadataCorpus: [],
  availableRerankerProviders: ["similarity"] satisfies RerankerProvider[],
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

  it("shows empty metadata controls when the corpus has no keys", () => {
    render(<AdvancedRetrievalDrawer {...baseProps} open />);

    expect(
      screen.getByText("No metadata on the current documents.")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("metadata-filter-key")).not.toBeInTheDocument();
  });

  it("emits metadata_filter when a key and value are chosen", async () => {
    const onMetadataFilterChange = vi.fn();
    function DrawerWithFilterState() {
      const [state, setState] = useState<AdvancedRetrievalState>({ explicit: {} });
      return (
        <AdvancedRetrievalDrawer
          {...baseProps}
          open
          state={state}
          onMetadataFilterChange={(filter: DocumentScalarMetadata | undefined) => {
            onMetadataFilterChange(filter);
            setState({
              explicit: filter ? { metadataFilter: filter } : {},
            });
          }}
          metadataCorpus={[
            { metadata: { department: "legal" } },
            { metadata: { department: "hr" } },
          ]}
        />
      );
    }

    render(<DrawerWithFilterState />);

    await userEvent.selectOptions(
      screen.getByTestId("metadata-filter-key"),
      "department"
    );
    expect(onMetadataFilterChange).toHaveBeenCalledWith({
      department: "hr",
    });

    await userEvent.selectOptions(
      screen.getByTestId("metadata-filter-value"),
      "legal"
    );
    expect(onMetadataFilterChange).toHaveBeenLastCalledWith({
      department: "legal",
    });
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

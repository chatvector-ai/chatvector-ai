import { describe, it, expect, vi } from "vitest";

vi.mock("../lib/session", () => ({ getSessionId: () => "test-session-id" }));
import { useState } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AdvancedRetrievalState, RerankerProvider } from "../lib/advancedRetrieval";
import { buildChatRequestBody } from "../lib/buildChatBody";
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
  onPresetChange: vi.fn(),
  metadataCorpus: [],
  availablePresets: [],
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

  it("lists only discovery preset names", () => {
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        availablePresets={["alpha", "beta"]}
      />
    );

    const picker = screen.getByTestId("retrieval-preset-picker");
    expect(picker).toContainHTML("alpha");
    expect(picker).toContainHTML("beta");
    expect(picker).not.toContainHTML("hybrid");
  });

  it("renders an empty preset picker when discovery returns no names", () => {
    render(<AdvancedRetrievalDrawer {...baseProps} open availablePresets={[]} />);

    const options = screen
    .getByTestId("retrieval-preset-picker")
    .querySelectorAll("option");
    expect(options).toHaveLength(1);
    expect(options[0]).toHaveTextContent("None");
  });

  it("names preset env vars in the empty state when no presets are loaded", () => {
    render(<AdvancedRetrievalDrawer {...baseProps} open availablePresets={[]} />);

    expect(screen.getByText(/No presets are loaded/i)).toBeInTheDocument();
    expect(screen.getByText("RETRIEVAL_PRESETS_PATH")).toBeInTheDocument();
    expect(screen.getByText("RETRIEVAL_PRESETS")).toBeInTheDocument();
    expect(screen.getByText("backend/.env.example")).toBeInTheDocument();
    expect(
      screen.getByText("documentation/content/api-reference.md")
    ).toBeInTheDocument();
    expect(screen.getByText(/at API startup/i)).toBeInTheDocument();
  });

  it("calls onPresetChange when a preset is selected", async () => {
    const onPresetChange = vi.fn();
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        availablePresets={["alpha", "beta"]}
        onPresetChange={onPresetChange}
      />
    );

    await userEvent.selectOptions(
      screen.getByTestId("retrieval-preset-picker"),
      "alpha"
    );
    expect(onPresetChange).toHaveBeenCalledWith("alpha");
  });

  it("labels each omitted boolean independently when hybrid is explicit", () => {
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        state={{ explicit: { hybridEnabled: true } }}
      />
    );

    expect(screen.getByTestId("hybrid-inherit-label")).toHaveTextContent(
      /Explicit override/
    );
    expect(screen.getByTestId("reranking-inherit-label")).toHaveTextContent(
      /Process default/
    );
    expect(screen.getByTestId("query-transformation-inherit-label")).toHaveTextContent(
      /Process default/
    );
    expect(screen.getByTestId("history-aware-inherit-label")).toHaveTextContent(
      /Process default/
    );
  });

  it("with empty preset discovery, explicit match count is sent without preset", async () => {
    let latestState: AdvancedRetrievalState = { explicit: {} };
    function DrawerWithMatchCount() {
      const [state, setState] = useState<AdvancedRetrievalState>({ explicit: {} });
      latestState = state;
      return (
        <AdvancedRetrievalDrawer
          {...baseProps}
          open
          availablePresets={[]}
          state={state}
          onMatchCountChange={(matchCount) =>
            setState((prev) => ({
              explicit: { ...prev.explicit, matchCount },
            }))
          }
        />
      );
    }

    render(<DrawerWithMatchCount />);

    expect(screen.getByTestId("retrieval-preset-picker")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("match-count-set-explicit"));
    const numberInput = screen.getByRole("spinbutton", { name: /match count/i });
    fireEvent.change(numberInput, { target: { value: "11" } });

    await waitFor(() => {
      expect(latestState.explicit.matchCount).toBe(11);
    });

    const body = buildChatRequestBody({
      question: "q",
      docId: "doc-1",
      retrieval: latestState,
    });

    expect(body).not.toHaveProperty("retrieval");
    expect(body.match_count).toBe(11);
  });

  it("omitted match count shows inherit label without a concrete digit", () => {
    render(<AdvancedRetrievalDrawer {...baseProps} open />);

    const label = screen.getByTestId("match-count-inherit-label");
    expect(label).toHaveTextContent(/process default/i);
    expect(label.textContent).not.toMatch(/\(\s*\d+\s*\)/);
  });

  it("does not commit match count until the user sets a value", async () => {
    let latestState: AdvancedRetrievalState = { explicit: {} };
    function DrawerProbe() {
      const [state, setState] = useState<AdvancedRetrievalState>({ explicit: {} });
      latestState = state;
      return (
        <AdvancedRetrievalDrawer
          {...baseProps}
          open
          state={state}
          onMatchCountChange={(matchCount) =>
            setState((prev) => ({
              explicit: { ...prev.explicit, matchCount },
            }))
          }
        />
      );
    }

    render(<DrawerProbe />);
    await userEvent.click(screen.getByTestId("match-count-set-explicit"));
    expect(latestState.explicit.matchCount).toBeUndefined();
    expect(
      buildChatRequestBody({ question: "q", docId: "d", retrieval: latestState })
    ).not.toHaveProperty("match_count");
  });

  it("history window editors stay unset until the user enters a value", async () => {
    const onRetrieval = vi.fn();
    const onGeneration = vi.fn();
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        onRetrievalHistoryWindowChange={onRetrieval}
        onGenerationHistoryWindowChange={onGeneration}
      />
    );

    await userEvent.click(
      screen.getByRole("button", { name: /set retrieval history window/i })
    );
    await userEvent.click(
      screen.getByRole("button", { name: /set generation history window/i })
    );
    expect(onRetrieval).not.toHaveBeenCalled();
    expect(onGeneration).not.toHaveBeenCalled();
  });

  it("explains session-scope filter behavior without naming a document when none is active", async () => {
    render(<AdvancedRetrievalDrawer {...baseProps} open />);

    await userEvent.click(screen.getByRole("button", { name: "Metadata filter help" }));

    expect(
      screen.getByText(/exact match on document metadata keys/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /under session scope, the filter can only narrow the active document/i
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(/to filter across the library, use tenant scope/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/active document \(/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/if it does not match, the question returns an error/i)
    ).toBeInTheDocument();
  });

  it("names the active document in metadata filter help when one is attached", async () => {
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        activeDocumentFileName="handbook.pdf"
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Metadata filter help" }));

    expect(
      screen.getByText(/active document \(handbook\.pdf\)/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/to filter across the library, use tenant scope/i)
    ).toBeInTheDocument();
  });

  it("does not select session or tenant scope when only a preset is active", () => {
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        state={{ explicit: { preset: "alpha" } }}
        availablePresets={["alpha"]}
      />
    );

    expect(
      screen.getByRole("radio", { name: /session/i })
    ).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /tenant/i })).not.toBeChecked();
    expect(screen.getByTestId("scope-inherit-label")).toHaveTextContent(
      /Follows selected preset/
    );
  });

  it("renders history-aware retrieval as a three-state control defaulting to Default", () => {
    render(<AdvancedRetrievalDrawer {...baseProps} open />);

    const radiogroup = screen.getByRole("radiogroup", {
      name: "History-aware retrieval",
    });
    expect(radiogroup).toBeInTheDocument();

    const defaultRadio = within(radiogroup).getByRole("radio", { name: "Default" });
    const onRadio = within(radiogroup).getByRole("radio", { name: "On" });
    const offRadio = within(radiogroup).getByRole("radio", { name: "Off" });

    expect(defaultRadio).toBeChecked();
    expect(onRadio).not.toBeChecked();
    expect(offRadio).not.toBeChecked();
  });

  it("selects On when explicit historyAwareRetrieval is true and Off when false", () => {
    const { rerender } = render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        state={{ explicit: { historyAwareRetrieval: true } }}
      />
    );

    const radiogroup = screen.getByRole("radiogroup", {
      name: "History-aware retrieval",
    });
    expect(within(radiogroup).getByRole("radio", { name: "On" })).toBeChecked();
    expect(within(radiogroup).getByRole("radio", { name: "Default" })).not.toBeChecked();

    rerender(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        state={{ explicit: { historyAwareRetrieval: false } }}
      />
    );
    expect(within(radiogroup).getByRole("radio", { name: "Off" })).toBeChecked();
    expect(within(radiogroup).getByRole("radio", { name: "Default" })).not.toBeChecked();
  });

  it("calls onHistoryAwareRetrievalChange with true, false, and undefined when options are clicked", async () => {
    const onHistoryAwareRetrievalChange = vi.fn();
    const user = userEvent.setup();

    function DrawerWrapper() {
      const [historyAware, setHistoryAware] = useState<boolean | undefined>(undefined);
      return (
        <AdvancedRetrievalDrawer
          {...baseProps}
          open
          state={{
            explicit:
              historyAware !== undefined
                ? { historyAwareRetrieval: historyAware }
                : {},
          }}
          onHistoryAwareRetrievalChange={(val) => {
            setHistoryAware(val);
            onHistoryAwareRetrievalChange(val);
          }}
        />
      );
    }

    render(<DrawerWrapper />);

    const radiogroup = screen.getByRole("radiogroup", {
      name: "History-aware retrieval",
    });

    await user.click(within(radiogroup).getByRole("radio", { name: "On" }));
    expect(onHistoryAwareRetrievalChange).toHaveBeenLastCalledWith(true);

    await user.click(within(radiogroup).getByRole("radio", { name: "Off" }));
    expect(onHistoryAwareRetrievalChange).toHaveBeenLastCalledWith(false);

    await user.click(within(radiogroup).getByRole("radio", { name: "Default" }));
    expect(onHistoryAwareRetrievalChange).toHaveBeenLastCalledWith(undefined);
  });

  it("shows inherited history values when defaults are provided (history off, windows 3 and 4)", () => {
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        defaults={{
          history_aware_retrieval: false,
          retrieval_history_window: 3,
          generation_history_window: 4,
        }}
      />
    );

    const radiogroup = screen.getByRole("radiogroup", {
      name: "History-aware retrieval",
    });
    const defaultRadio = within(radiogroup).getByRole("radio", {
      name: "Default · Off",
    });
    expect(defaultRadio).toBeInTheDocument();
    expect(defaultRadio).toBeChecked();

    expect(screen.getByText("Default: 3")).toBeInTheDocument();
    expect(screen.getByText("Default: 4")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /set retrieval history window/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /set generation history window/i })
    ).toBeInTheDocument();
  });

  it("shows 'Default · On' when defaults specifies history_aware_retrieval as true", () => {
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        defaults={{
          history_aware_retrieval: true,
          retrieval_history_window: 6,
          generation_history_window: 10,
        }}
      />
    );

    const radiogroup = screen.getByRole("radiogroup", {
      name: "History-aware retrieval",
    });
    const defaultRadio = within(radiogroup).getByRole("radio", {
      name: "Default · On",
    });
    expect(defaultRadio).toBeInTheDocument();
    expect(defaultRadio).toBeChecked();
    expect(screen.getByText("Default: 6")).toBeInTheDocument();
    expect(screen.getByText("Default: 10")).toBeInTheDocument();
  });

  it("shows neutral 'Default' and no window numbers when defaults is absent", () => {
    render(<AdvancedRetrievalDrawer {...baseProps} open defaults={undefined} />);

    const radiogroup = screen.getByRole("radiogroup", {
      name: "History-aware retrieval",
    });
    const defaultRadio = within(radiogroup).getByRole("radio", {
      name: "Default",
    });
    expect(defaultRadio).toBeInTheDocument();
    expect(defaultRadio).toBeChecked();

    expect(screen.queryByText(/Default:/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /set retrieval history window/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /set generation history window/i })
    ).toBeInTheDocument();
  });

  it("keeps explicit values visually distinct from defaults", () => {
    render(
      <AdvancedRetrievalDrawer
        {...baseProps}
        open
        defaults={{
          history_aware_retrieval: false,
          retrieval_history_window: 3,
          generation_history_window: 4,
        }}
        state={{
          explicit: {
            historyAwareRetrieval: true,
            retrievalHistoryWindow: 7,
            generationHistoryWindow: 12,
          },
        }}
      />
    );

    const radiogroup = screen.getByRole("radiogroup", {
      name: "History-aware retrieval",
    });
    expect(within(radiogroup).getByRole("radio", { name: "On" })).toBeChecked();
    expect(within(radiogroup).getByRole("radio", { name: "Default · Off" })).not.toBeChecked();
    expect(screen.getByTestId("history-aware-inherit-label")).toHaveTextContent(
      /Explicit override/
    );

    const inputs = screen.getAllByRole("spinbutton");
    const values = inputs.map((input) => (input as HTMLInputElement).value);
    expect(values).toContain("7");
    expect(values).toContain("12");
  });
});

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RetrievalSettingsPanel from "./RetrievalSettingsPanel";
import { DEFAULT_RETRIEVAL_SETTINGS } from "../lib/retrievalSettings";

describe("RetrievalSettingsPanel", () => {
  it("calls scope and match count handlers when controls change", async () => {
    const onScopeChange = vi.fn();
    const onMatchCountChange = vi.fn();

    render(
      <RetrievalSettingsPanel
        settings={DEFAULT_RETRIEVAL_SETTINGS}
        onScopeChange={onScopeChange}
        onMatchCountChange={onMatchCountChange}
      />
    );

    await userEvent.click(screen.getByText("Retrieval settings"));

    await userEvent.click(screen.getByRole("radio", { name: "Tenant" }));
    expect(onScopeChange).toHaveBeenCalledWith("tenant");

    const matchCountInput = screen.getByRole("spinbutton", { name: "Match count" });
    await userEvent.clear(matchCountInput);
    await userEvent.type(matchCountInput, "8");
    expect(onMatchCountChange).toHaveBeenCalled();
  });

  it("hides scope controls when showScope is false", async () => {
    render(
      <RetrievalSettingsPanel
        settings={DEFAULT_RETRIEVAL_SETTINGS}
        onMatchCountChange={vi.fn()}
        showScope={false}
      />
    );

    await userEvent.click(screen.getByText("Retrieval settings"));

    expect(screen.queryByRole("radiogroup", { name: "Retrieval scope" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scope help" })).not.toBeInTheDocument();
    expect(screen.getByRole("slider")).toBeInTheDocument();
  });

  it("calls onInspectModeChange when the inspect toggle changes", async () => {
    const onInspectModeChange = vi.fn();

    render(
      <RetrievalSettingsPanel
        settings={DEFAULT_RETRIEVAL_SETTINGS}
        onMatchCountChange={vi.fn()}
        inspectMode={false}
        onInspectModeChange={onInspectModeChange}
      />
    );

    await userEvent.click(screen.getByText("Retrieval settings"));
    await userEvent.click(
      screen.getByRole("checkbox", { name: /request retrieval debug payload/i })
    );
    expect(onInspectModeChange).toHaveBeenCalledWith(true);
  });

  it("explains selected-document session scope and ready-document tenant scope in the help popover", async () => {
    render(
      <RetrievalSettingsPanel
        settings={DEFAULT_RETRIEVAL_SETTINGS}
        onScopeChange={vi.fn()}
        onMatchCountChange={vi.fn()}
      />
    );

    await userEvent.click(screen.getByText("Retrieval settings"));
    await userEvent.click(screen.getByRole("button", { name: "Scope help" }));

    expect(
      screen.getByText(/searches only the selected document attached to this chat/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /searches the tenant's ready documents, which can include documents other than the attached chip/i
      )
    ).toBeInTheDocument();
  });
});

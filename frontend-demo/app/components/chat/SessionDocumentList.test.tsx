import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SessionDocumentList from "./SessionDocumentList";
import type { AdvancedRetrievalState } from "../../lib/advancedRetrieval";
import type { DocumentSummary } from "../../lib/api";

const mockSummaries: DocumentSummary[] = [
  {
    document_id: "doc-1",
    file_name: "policy-2024.pdf",
    status: "completed",
    created_at: null,
    updated_at: null,
  },
  {
    document_id: "doc-2",
    file_name: "span-notes.txt",
    status: "completed",
    created_at: null,
    updated_at: null,
  },
  {
    document_id: "doc-3",
    file_name: "draft.md",
    status: "processing",
    created_at: null,
    updated_at: null,
  },
];

describe("SessionDocumentList", () => {
  const sessionRetrievalState: AdvancedRetrievalState = {
    explicit: { scope: "session" },
  };

  const tenantRetrievalState: AdvancedRetrievalState = {
    explicit: { scope: "tenant" },
  };

  it("returns null when session has no documents", () => {
    const { container } = render(
      <SessionDocumentList
        sessionDocumentIds={[]}
        documentSummaries={mockSummaries}
        retrievalState={sessionRetrievalState}
        attachment={null}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders P6-W2-04 truthful labels under session scope for multiple documents", () => {
    render(
      <SessionDocumentList
        sessionDocumentIds={["doc-1", "doc-2"]}
        documentSummaries={mockSummaries}
        retrievalState={sessionRetrievalState}
        attachment={{
          documentId: "doc-1",
          fileName: "policy-2024.pdf",
          status: "ready",
          statusEndpoint: "/documents/doc-1/status",
        }}
        activeDocumentId="doc-1"
        onMakeActive={vi.fn()}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(
      screen.getByText("Session documents — only the active document is searched")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("tenant-scope-notice")).not.toBeInTheDocument();

    const activeSearched = screen.getByTestId("document-active-searched");
    const notSearched = screen.getByTestId("document-not-searched");

    expect(activeSearched).toHaveTextContent("Active · searched");
    expect(notSearched).toHaveTextContent("Not searched");
    expect(
      screen.getByTestId("document-list-row-doc-1").contains(activeSearched)
    ).toBe(true);
    expect(
      screen.getByTestId("document-list-row-doc-2").contains(notSearched)
    ).toBe(true);
  });

  it("renders In scope badge under session scope for single document session", () => {
    render(
      <SessionDocumentList
        sessionDocumentIds={["doc-1"]}
        documentSummaries={mockSummaries}
        retrievalState={sessionRetrievalState}
        attachment={{
          documentId: "doc-1",
          fileName: "policy-2024.pdf",
          status: "ready",
          statusEndpoint: "/documents/doc-1/status",
        }}
        activeDocumentId="doc-1"
        onReplace={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getByText("Session documents")).toBeInTheDocument();
    expect(screen.queryByText(/only the active document is searched/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("document-in-active-scope")).toHaveTextContent("In scope");
    expect(screen.queryByTestId("tenant-scope-notice")).not.toBeInTheDocument();
  });

  it("renders tenant scope line with ready document count and removes per-row scope badges under tenant scope", () => {
    const onMakeActive = vi.fn();
    render(
      <SessionDocumentList
        sessionDocumentIds={["doc-1", "doc-2"]}
        documentSummaries={mockSummaries}
        retrievalState={tenantRetrievalState}
        attachment={{
          documentId: "doc-1",
          fileName: "policy-2024.pdf",
          status: "ready",
          statusEndpoint: "/documents/doc-1/status",
        }}
        activeDocumentId="doc-1"
        onMakeActive={onMakeActive}
        onReplace={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expect(screen.getByText("Session documents")).toBeInTheDocument();
    const notice = screen.getByTestId("tenant-scope-notice");
    expect(notice).toHaveTextContent(
      "Tenant scope searches all ready documents in the tenant (2), which can include documents not shown here."
    );

    // No row claims to be the search set
    expect(screen.queryByTestId("document-in-active-scope")).not.toBeInTheDocument();
    expect(screen.queryByTestId("document-active-searched")).not.toBeInTheDocument();
    expect(screen.queryByTestId("document-not-searched")).not.toBeInTheDocument();
    expect(screen.queryByTestId("document-scope-follows-preset")).not.toBeInTheDocument();

    // Session rows remain visible as neutral in this session, with actions available
    const row2 = screen.getByTestId("document-list-row-doc-2");
    expect(row2).toHaveTextContent("span-notes.txt");
    const makeActiveButton = within(row2).getByRole("button", {
      name: "Make span-notes.txt active",
    });
    expect(makeActiveButton).toBeInTheDocument();
  });

  it("omits count from tenant scope line when documents are paginated", () => {
    render(
      <SessionDocumentList
        sessionDocumentIds={["doc-1"]}
        documentSummaries={mockSummaries}
        retrievalState={tenantRetrievalState}
        attachment={{
          documentId: "doc-1",
          fileName: "policy-2024.pdf",
          status: "ready",
          statusEndpoint: "/documents/doc-1/status",
        }}
        activeDocumentId="doc-1"
        onReplace={vi.fn()}
        onDelete={vi.fn()}
        isDocumentsPaginated={true}
      />
    );

    const notice = screen.getByTestId("tenant-scope-notice");
    expect(notice).toHaveTextContent(
      "Tenant scope searches all ready documents in the tenant, which can include documents not shown here."
    );
    expect(notice).not.toHaveTextContent("(2)");
  });
});

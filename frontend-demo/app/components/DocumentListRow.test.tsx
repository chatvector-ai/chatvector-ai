import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import DocumentListRow from "./DocumentListRow";

describe("DocumentListRow scope labels", () => {
  it("shows preset-follows copy when scope membership is preset-controlled", () => {
    render(
      <DocumentListRow
        documentId="doc-1"
        fileName="notes.txt"
        fileType="txt"
        status="completed"
        failureDetail={null}
        inActiveScope="follows-preset"
      />,
    );

    expect(screen.getByTestId("document-scope-follows-preset")).toHaveTextContent(
      "Scope follows preset",
    );
    expect(screen.queryByTestId("document-in-active-scope")).not.toBeInTheDocument();
  });

  it("does not show scope labels for unavailable session documents", () => {
    render(
      <DocumentListRow
        documentId="doc-missing"
        fileName=""
        fileType="file"
        status="unavailable"
        failureDetail={null}
        unavailable
      />,
    );

    expect(
      screen.queryByTestId("document-scope-follows-preset"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("document-in-active-scope")).not.toBeInTheDocument();
  });

  it("shows in-scope for explicit session selection", () => {
    render(
      <DocumentListRow
        documentId="doc-a"
        fileName="a.txt"
        fileType="txt"
        status="completed"
        failureDetail={null}
        inActiveScope
      />,
    );

    expect(screen.getByTestId("document-in-active-scope")).toHaveTextContent(
      "In scope",
    );
  });

  it("omits in-scope badge when explicitly out of session scope", () => {
    render(
      <DocumentListRow
        documentId="doc-b"
        fileName="b.txt"
        fileType="txt"
        status="completed"
        failureDetail={null}
        inActiveScope={false}
      />,
    );

    expect(screen.queryByTestId("document-in-active-scope")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("document-scope-follows-preset"),
    ).not.toBeInTheDocument();
  });
});

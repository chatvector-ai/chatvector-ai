import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import DocumentListRow from "./DocumentListRow";

describe("DocumentListRow scope labels", () => {
  it("shows preset-follows copy when active scope membership is unknown", () => {
    render(
      <DocumentListRow
        documentId="doc-1"
        fileName="notes.txt"
        fileType="txt"
        status="completed"
        failureDetail={null}
        inActiveScope={null}
      />,
    );

    expect(screen.getByTestId("document-scope-follows-preset")).toHaveTextContent(
      "Scope follows preset",
    );
    expect(screen.queryByTestId("document-in-active-scope")).not.toBeInTheDocument();
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  describe("DocumentListRow Make active action", () => {
    it("renders 'Make active' button when onMakeActive is provided on ready rows", () => {
      const onMakeActive = vi.fn();
      render(
        <DocumentListRow
          documentId="doc-2"
          fileName="report.pdf"
          fileType="pdf"
          status="completed"
          failureDetail={null}
          onMakeActive={onMakeActive}
        />,
      );

      const button = screen.getByRole("button", {
        name: "Make report.pdf active",
      });
      expect(button).toBeInTheDocument();
      expect(button).toBeEnabled();
      expect(button).toHaveTextContent("Make active");
    });

    it("does not render 'Make active' button when onMakeActive is not provided", () => {
      render(
        <DocumentListRow
          documentId="doc-1"
          fileName="notes.txt"
          fileType="txt"
          status="completed"
          failureDetail={null}
        />,
      );

      expect(
        screen.queryByRole("button", { name: /make.*active/i }),
      ).not.toBeInTheDocument();
    });

    it("disables 'Make active' when disabled prop is true (e.g. response in flight)", () => {
      render(
        <DocumentListRow
          documentId="doc-2"
          fileName="report.pdf"
          fileType="pdf"
          status="completed"
          failureDetail={null}
          onMakeActive={vi.fn()}
          disabled
        />,
      );

      const button = screen.getByRole("button", {
        name: "Make report.pdf active",
      });
      expect(button).toBeDisabled();
    });

    it("disables 'Make active' when row is not ready (e.g. processing or failed)", () => {
      render(
        <DocumentListRow
          documentId="doc-3"
          fileName="incoming.pdf"
          fileType="pdf"
          status="processing"
          failureDetail={null}
          onMakeActive={vi.fn()}
        />,
      );

      const button = screen.getByRole("button", {
        name: "Make incoming.pdf active",
      });
      expect(button).toBeDisabled();
    });

    it("calls onMakeActive when clicked", async () => {
      const onMakeActive = vi.fn();
      render(
        <DocumentListRow
          documentId="doc-2"
          fileName="report.pdf"
          fileType="pdf"
          status="completed"
          failureDetail={null}
          onMakeActive={onMakeActive}
        />,
      );

      await userEvent.click(
        screen.getByRole("button", { name: "Make report.pdf active" }),
      );
      expect(onMakeActive).toHaveBeenCalledTimes(1);
    });
  });
});

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import SdkPage from "./page";

describe("SdkPage", () => {
  it("checks status before printing answer in the quickstart sample", () => {
    const { container } = render(<SdkPage />);
    const text = container.textContent ?? "";
    expect(text).toContain('if answer.status == "ok":');
    expect(text).toContain("print(answer.answer)");
  });

  it("renders a visible pointer to the TypeScript SDK with package name and link to its README", () => {
    const { container } = render(<SdkPage />);
    const text = container.textContent ?? "";
    expect(text).toContain("@chatvector/sdk");

    const links = screen.getAllByRole("link");
    const tsLinks = links.filter((link) =>
      link.getAttribute("href")?.includes("sdk/typescript/README.md")
    );
    expect(tsLinks.length).toBeGreaterThanOrEqual(1);
    for (const link of tsLinks) {
      expect(link).toHaveAttribute("target", "_blank");
    }
  });
});

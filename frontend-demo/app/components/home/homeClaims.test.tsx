import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import Developers from "./Developers";
import Features from "./Features";
import Hero from "./Hero";
import WhatIs from "./WhatIs";

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const FORBIDDEN_PATTERNS = [
  /hallucinat/i,
  /any document/i,
  /cited,\s*accurate/i,
  /hybrid vector/i,
  /no cloud dependency/i,
  /not hallucinated/i,
  /no hallucinations/i,
];

function collectHomeText(...containers: HTMLElement[]): string {
  return containers.map((el) => el.textContent ?? "").join("\n");
}

describe("homepage claims", () => {
  it("does not include misleading forbidden phrases in home sections", () => {
    const { container: developersRoot } = render(<Developers />);
    const { container: featuresRoot } = render(<Features />);
    const { container: heroRoot } = render(<Hero />);
    const { container: whatIsRoot } = render(<WhatIs />);

    const text = collectHomeText(
      developersRoot,
      featuresRoot,
      heroRoot,
      whatIsRoot
    );

    for (const pattern of FORBIDDEN_PATTERNS) {
      expect(text).not.toMatch(pattern);
    }
  });

  it("describes optional hybrid retrieval and supported upload formats", () => {
    const { container: featuresRoot } = render(<Features />);
    const { container: whatIsRoot } = render(<WhatIs />);

    const text = collectHomeText(featuresRoot, whatIsRoot);

    expect(text).toMatch(/optional hybrid search/i);
    expect(text).toMatch(/vector retrieval by default/i);
    expect(text).toMatch(/PDF, TXT, Markdown, HTML, and DOCX/i);
  });

  it("describes Gemini as recommended, not required, with other providers supported", () => {
    const { container: featuresRoot } = render(<Features />);
    const { container: whatIsRoot } = render(<WhatIs />);

    const text = collectHomeText(featuresRoot, whatIsRoot);

    expect(text).toMatch(/Gemini is the recommended default/i);
    expect(text).toMatch(/OpenAI and Ollama/i);
    expect(text).not.toMatch(/Powered by Google Gemini/i);
  });

  it("frames the HTTP API as the product and keeps Try the Demo in the hero", () => {
    render(<Hero />);

    expect(
      screen.getByText(/HTTP API/i, { exact: false })
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Try the Demo" })).toHaveAttribute(
      "href",
      "/chat"
    );
    expect(screen.getByText(/Grounded, with citations/i)).toBeInTheDocument();
  });
});

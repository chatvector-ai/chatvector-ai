import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import GettingStartedPage from "./page";

describe("GettingStartedPage", () => {
  it("documents make quickstart before manual docker compose and avoids Google-key-required copy", () => {
    const { container } = render(<GettingStartedPage />);
    const text = container.textContent ?? "";

    const quickstartIndex = text.indexOf("make quickstart");
    const composeIndex = text.indexOf("docker compose up --build");
    expect(quickstartIndex).toBeGreaterThanOrEqual(0);
    expect(composeIndex).toBeGreaterThanOrEqual(0);
    expect(quickstartIndex).toBeLessThan(composeIndex);

    expect(text).not.toMatch(/Google AI Studio API key/i);

    expect(text).toContain("Gemini");
    expect(text).toContain("OpenAI");
    expect(text).toContain("Ollama");
    expect(text).toContain("DOCX");
    expect(text).toContain("not OCR");

    expect(text).toMatch(/vector-only/i);
    expect(text).toMatch(/Hybrid search/i);
    expect(text).toMatch(/reranking/i);
    expect(text).toMatch(/Follow-up questions/i);
  });
});

import Link from "next/link";

import { GITHUB_REPO, SYNTAX } from "../../lib/constants";
import CodeBlock from "../CodeBlock";

function HeroCodeBlock() {
 const codeLines = [
  {
    parts: [
      { c: SYNTAX.kw, t: "from " },
      { c: SYNTAX.plain, t: "chatvector " },
      { c: SYNTAX.kw, t: "import " },
      { c: SYNTAX.fn, t: "ChatVectorClient" },
    ],
  },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  {
    parts: [{ c: SYNTAX.cm, t: "# Point the client at your running instance" }],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "cv = " },
      { c: SYNTAX.fn, t: "ChatVectorClient" },
      { c: SYNTAX.plain, t: "(" },
      { c: SYNTAX.str, t: '"http://localhost:8000"' },
      { c: SYNTAX.plain, t: ")" },
    ],
  },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  {
    parts: [{ c: SYNTAX.cm, t: "# Upload a document" }],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "doc = cv." },
      { c: SYNTAX.fn, t: "upload_document" },
      { c: SYNTAX.plain, t: "(" },
      { c: SYNTAX.str, t: '"contract.pdf"' },
      { c: SYNTAX.plain, t: ")" },
    ],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "cv." },
      { c: SYNTAX.fn, t: "wait_for_ready" },
      { c: SYNTAX.plain, t: "(doc.document_id)" },
    ],
  },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  {
    parts: [{ c: SYNTAX.cm, t: "# Get a grounded, cited answer" }],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "answer = cv." },
      { c: SYNTAX.fn, t: "chat" },
      { c: SYNTAX.plain, t: "(" },
      { c: SYNTAX.str, t: '"What are the payment terms?"' },
      { c: SYNTAX.plain, t: ", doc.document_id)" },
    ],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "print(answer.answer)  " },
      { c: SYNTAX.cm, t: "# Cited, accurate" },
    ],
  },
];
  return (
    <div className="relative z-[1] mt-12 w-full max-w-[700px]">
      <CodeBlock language="python" filename="quickstart.py">
        {codeLines.map((line, i) => (
              <div key={i}>
                {line.parts.map((p, j) => (
                  <span key={j} style={{ color: p.c }}>
                    {p.t}
                  </span>
                ))}
              </div>
            ))}
      </CodeBlock>
    </div>
  );
}

export default function Hero() {
  return (
    <section
      id="hero"
      className="relative flex min-h-[90vh] flex-col items-center justify-center overflow-hidden px-8 pb-16 pt-20 text-center"
    >
      {/* Repeating grid: two linear-gradients referencing --border — Tailwind cannot express this */}
      <div
        className="pointer-events-none absolute inset-0 opacity-30"
        style={{
          backgroundImage:
            "linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }}
      />
      {/* Radial glow — Tailwind cannot express arbitrary radial-gradient */}
      <div
        className="pointer-events-none absolute left-1/2 top-[20%] h-[300px] w-[600px] -translate-x-1/2"
        style={{
          background:
            "radial-gradient(ellipse,rgba(0,229,160,0.13) 0%,transparent 70%)",
        }}
      />
      {/* Hero chip: sub-10% alpha on accent — kept inline for exact rgba match */}
      <div
        className="relative z-[1] mb-8 inline-flex items-center gap-2 rounded-full px-[18px] py-1.5 font-mono text-[0.8rem] text-accent"
        style={{
          background: "rgba(0,229,160,0.08)",
          border: "1px solid rgba(0,229,160,0.25)",
        }}
      >
        <span className="size-[7px] rounded-full bg-accent [animation:pulse_2s_infinite]" />
        Open-source · RAG Engine for Developers
      </div>

      <h1 className="relative z-[1] max-w-[820px] text-[clamp(2.4rem,5vw,4.2rem)] font-semibold leading-[1.12] tracking-[-1.5px] text-foreground">
        Build RAG apps that{" "}
        <span className="bg-gradient-to-r from-accent to-blue bg-clip-text text-transparent">
          actually understand
        </span>{" "}
        your data.
      </h1>

      <p className="relative z-[1] mx-auto mt-6 max-w-[540px] text-[1.2rem] font-light leading-[1.7] text-muted">
        ChatVector is a high-performance retrieval-augmented generation engine —
        ingest any document, retrieve semantically, and get LLM-powered answers
        in minutes.
      </p>

      <div className="relative z-[1] mt-10 flex flex-wrap justify-center gap-4">
        <a
          href={GITHUB_REPO}
          className="flex cursor-pointer items-center gap-2 rounded-lg border-none bg-accent px-7 py-3 text-[1rem] font-semibold text-black no-underline transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(0,229,160,0.25)]"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.44 9.8 8.2 11.38.6.11.82-.26.82-.57v-2c-3.34.72-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.09-.74.08-.73.08-.73 1.21.08 1.84 1.24 1.84 1.24 1.07 1.83 2.81 1.3 3.5 1 .11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.12-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 3-.4c1.02 0 2.04.14 3 .4 2.28-1.55 3.29-1.23 3.29-1.23.66 1.66.24 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.63-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.21.69.82.57C20.56 21.8 24 17.3 24 12c0-6.63-5.37-12-12-12z" />
          </svg>
          View on GitHub
        </a>
        <Link
          href="/chat"
          className="flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-7 py-3 text-[1rem] font-medium text-foreground no-underline transition-all duration-200 hover:border-[rgb(61,69,85)] hover:bg-surface"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
          Try the Demo
        </Link>
      </div>

      <HeroCodeBlock />
    </section>
  );
}

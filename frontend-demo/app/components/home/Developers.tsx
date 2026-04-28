import { Kicker } from "@/app/components/Kicker";

import { SYNTAX } from "../../lib/constants";
import CodeBlock from "../CodeBlock";

const DEV_POINTS = [
  {
    title: "Deploy anywhere",
    desc: "Run as a Docker container on your laptop, your server, or any cloud VM.",
  },
  {
    title: "Integrate via HTTP",
    desc: "Use the Python SDK or call the REST API directly from any language.",
  },
  {
    title: "Type-safe Python SDK",
    desc: "Full type hints. IDE autocomplete works out of the box.",
  },
  {
    title: "Community-first",
    desc: "MIT licensed. PRs welcome. Good first issues available.",
  },
];

export default function Developers() {
  const codeLines = [
    { parts: [{ c: SYNTAX.cm, t: "# Upload and wait for processing" }] },
    {
      parts: [
        { c: SYNTAX.plain, t: "doc = cv." },
        { c: SYNTAX.fn, t: "upload_document" },
        { c: SYNTAX.plain, t: "(" },
        { c: SYNTAX.str, t: '"report.pdf"' },
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
    { parts: [{ c: SYNTAX.cm, t: "# Ask questions against the document" }] },
    {
      parts: [
        { c: SYNTAX.plain, t: "answer = cv." },
        { c: SYNTAX.fn, t: "chat" },
        { c: SYNTAX.plain, t: "(" },
      ],
    },
    {
      parts: [
        { c: SYNTAX.plain, t: "  " },
        { c: SYNTAX.str, t: '"Summarise the key findings."' },
        { c: SYNTAX.plain, t: "," },
      ],
    },
    { parts: [{ c: SYNTAX.plain, t: "  doc.document_id" }] },
    { parts: [{ c: SYNTAX.plain, t: ")" }] },
    { parts: [{ c: SYNTAX.plain, t: " " }] },
    {
      parts: [{ c: SYNTAX.cm, t: "# Full response with source citations" }],
    },
    { parts: [{ c: SYNTAX.plain, t: "print(answer.answer)" }] },
    { parts: [{ c: SYNTAX.plain, t: "print(answer.sources)" }] },
  ];

  return (
    <section id="developers" className="bg-background px-8 py-24">
      <div className="mx-auto max-w-[1100px]">
        <Kicker spacing="lg">for developers</Kicker>
        <h2 className="mb-4 text-[clamp(1.8rem,3.5vw,2.8rem)] font-semibold leading-tight tracking-[-0.8px] text-foreground">
          Designed for people who
          <br />
          read the source code.
        </h2>
        <p className="mb-12 max-w-[540px] text-lg font-light leading-relaxed text-muted">
          Spin up an instance, point the SDK at it, and start querying your
          documents over HTTP. No magic, no lock-in — just a clean API you can
          read and trust.
        </p>

        <div className="grid grid-cols-1 items-center gap-12 md:grid-cols-2">
          <div className="flex flex-col gap-4">
            {DEV_POINTS.map((p) => (
              <div
                key={p.title}
                className="flex items-start gap-3.5 rounded-r-[10px] border border-border border-l-[3px] border-l-accent bg-surface py-4 pl-5 pr-4"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  className="mt-0.5 shrink-0 text-accent"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <div>
                  <h3 className="mb-0.5 text-lg font-medium text-foreground">
                    {p.title}
                  </h3>
                  <p className="m-0 text-lg leading-relaxed text-muted">
                    {p.desc}
                  </p>
                </div>
              </div>
            ))}
          </div>
          <CodeBlock language="python" filename="upload_and_chat.py">
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
      </div>
    </section>
  );
}

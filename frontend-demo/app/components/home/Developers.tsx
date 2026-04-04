import { SYNTAX } from "../../lib/constants";

const DEV_POINTS = [
  {
    title: "Zero vendor lock-in",
    desc: "Your models, your store, your infra. Switch anytime.",
  },
  {
    title: "Minimal dependencies",
    desc: "Lean core. Bring only what your stack needs.",
  },
  {
    title: "Type-safe Python API",
    desc: "Full type hints. IDE autocomplete works out of the box.",
  },
  {
    title: "Community-first",
    desc: "MIT licensed. PRs welcome. Good first issues available.",
  },
];

export default function Developers() {
  const codeLines = [
    { parts: [{ c: SYNTAX.cm, t: "# Swap components without rewriting" }] },
    {
      parts: [
        { c: SYNTAX.plain, t: "cv = " },
        { c: SYNTAX.fn, t: "ChatVector" },
        { c: SYNTAX.plain, t: "(" },
      ],
    },
    {
      parts: [
        { c: SYNTAX.plain, t: "  embedder=" },
        { c: SYNTAX.fn, t: "HuggingFaceEmbedder" },
        { c: SYNTAX.plain, t: "(" },
      ],
    },
    {
      parts: [
        { c: SYNTAX.plain, t: "    model=" },
        { c: SYNTAX.str, t: '"BAAI/bge-small-en"' },
      ],
    },
    { parts: [{ c: SYNTAX.plain, t: "  )," }] },
    {
      parts: [
        { c: SYNTAX.plain, t: "  store=" },
        { c: SYNTAX.fn, t: "ChromaStore" },
        { c: SYNTAX.plain, t: "(path=" },
        { c: SYNTAX.str, t: '"./db"' },
        { c: SYNTAX.plain, t: ")," },
      ],
    },
    {
      parts: [
        { c: SYNTAX.plain, t: "  llm=" },
        { c: SYNTAX.fn, t: "OllamaLLM" },
        { c: SYNTAX.plain, t: "(model=" },
        { c: SYNTAX.str, t: '"llama3"' },
        { c: SYNTAX.plain, t: ")," },
      ],
    },
    {
      parts: [
        { c: SYNTAX.plain, t: "  retriever=" },
        { c: SYNTAX.fn, t: "MMRRetriever" },
        { c: SYNTAX.plain, t: "(k=" },
        { c: "var(--accent)", t: "6" },
        { c: SYNTAX.plain, t: ")," },
      ],
    },
    { parts: [{ c: SYNTAX.plain, t: ")" }] },
    { parts: [] },
    { parts: [{ c: SYNTAX.cm, t: "# Full control, clean API" }] },
    {
      parts: [
        { c: SYNTAX.plain, t: "docs = cv." },
        { c: SYNTAX.fn, t: "retrieve" },
        { c: SYNTAX.plain, t: "(query, top_k=" },
        { c: "var(--accent)", t: "8" },
        { c: SYNTAX.plain, t: ")" },
      ],
    },
    {
      parts: [
        { c: SYNTAX.plain, t: "answer = cv." },
        { c: SYNTAX.fn, t: "generate" },
        { c: SYNTAX.plain, t: "(query, docs)" },
      ],
    },
  ];

  return (
    <section id="developers" className="bg-background px-8 py-24">
      <div className="mx-auto max-w-[1100px]">
        <p className="mb-4 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
          {"// built for developers"}
        </p>
        <h2 className="mb-4 text-[clamp(1.8rem,3.5vw,2.8rem)] font-semibold leading-tight tracking-[-0.8px] text-foreground">
          Designed for people who
          <br />
          read the source code.
        </h2>
        <p className="mb-12 max-w-[540px] text-[1.05rem] font-light leading-[1.7] text-muted">
          No drag-and-drop. No &quot;AI magic&quot;. Just clean Python APIs,
          sensible defaults, and full control when you need it.
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
                  <h4 className="mb-0.5 text-[0.92rem] font-medium text-foreground">
                    {p.title}
                  </h4>
                  <p className="m-0 text-[0.82rem] text-muted">{p.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="overflow-hidden rounded-xl border border-border bg-surface">
            <div className="flex items-center gap-2 border-b border-border bg-[rgb(24,28,34)] px-4 py-3">
              {/* macOS traffic-light dots — intentional non-token colors */}
              <div className="size-2.5 rounded-full bg-[rgb(255,95,87)]" />
              <div className="size-2.5 rounded-full bg-[rgb(254,188,46)]" />
              <div className="size-2.5 rounded-full bg-[rgb(40,200,64)]" />
              <span className="ml-auto font-mono text-xs text-muted">
                custom_pipeline.py
              </span>
            </div>
            <pre className="m-0 overflow-x-auto px-6 py-5 font-mono text-[0.82rem] leading-[1.75]">
              {codeLines.map((line, i) => (
                <div key={i}>
                  {line.parts.map((p, j) => (
                    <span key={j} style={{ color: p.c }}>
                      {p.t}
                    </span>
                  ))}
                </div>
              ))}
            </pre>
          </div>
        </div>
      </div>
    </section>
  );
}

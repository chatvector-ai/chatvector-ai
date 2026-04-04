"use client";

import Link from "next/link";
import { useState } from "react";

const GITHUB_REPO = "https://github.com/chatvector-ai/chatvector-ai";

/** Code-sample syntax colors (IDE-style); not part of the seven semantic tokens. */
const SYNTAX = {
  kw: "rgb(255, 123, 114)",
  fn: "rgb(121, 192, 255)",
  str: "rgb(165, 214, 255)",
  cm: "rgb(139, 148, 158)",
  plain: "rgb(201, 209, 217)",
} as const;

function HeroCodeBlock() {
  const lines = [
    { type: "kw", text: "from " },
    { type: "plain", text: "chatvector " },
    { type: "kw", text: "import " },
    { type: "fn", text: "ChatVector" },
    { type: "br" },
    { type: "br" },
    { type: "cm", text: "# Initialize the RAG engine" },
    { type: "br" },
    { type: "plain", text: "cv = " },
    { type: "fn", text: "ChatVector" },
    { type: "plain", text: "(model=" },
    { type: "str", text: '"mistral-7b"' },
    { type: "plain", text: ", vector_store=" },
    { type: "str", text: '"faiss"' },
    { type: "plain", text: ")" },
    { type: "br" },
    { type: "br" },
    { type: "cm", text: "# Ingest your documents" },
    { type: "br" },
    { type: "plain", text: "cv." },
    { type: "fn", text: "ingest" },
    { type: "plain", text: '("' },
    { type: "str", text: "./docs/" },
    { type: "plain", text: '", chunk_size=' },
    { type: "val", text: "512" },
    { type: "plain", text: ")" },
    { type: "br" },
    { type: "br" },
    { type: "cm", text: "# Get grounded, cited answers" },
    { type: "br" },
    { type: "plain", text: "answer = cv." },
    { type: "fn", text: "query" },
    { type: "plain", text: '("' },
    { type: "str", text: "What does the refund policy say?" },
    { type: "plain", text: '"' },
    { type: "plain", text: ")" },
    { type: "br" },
    { type: "kw", text: "print" },
    { type: "plain", text: "(answer.response)  " },
    { type: "cm", text: "# Cited, accurate" },
  ];

  return (
    <div className="mt-12 w-full max-w-[700px]">
      <div className="overflow-hidden rounded-xl border border-(--border) bg-(--surface)">
        <div className="flex items-center gap-2 border-b border-(--border) bg-[rgb(24,28,34)] px-4 py-3">
          <div className="size-2.5 rounded-full bg-[rgb(255,95,87)]" />
          <div className="size-2.5 rounded-full bg-[rgb(254,188,46)]" />
          <div className="size-2.5 rounded-full bg-[rgb(40,200,64)]" />
          <span className="ml-auto font-[family-name:JetBrains_Mono,monospace] text-xs text-(--muted)">
            quickstart.py
          </span>
        </div>
        {/* Each token uses inline `color` — driven by the highlight map above */}
        <pre className="m-0 overflow-x-auto px-6 py-5 font-[family-name:JetBrains_Mono,monospace] text-[0.82rem] leading-[1.75]">
          {lines.map((t, i) =>
            t.type === "br" ? (
              <br key={i} />
            ) : (
              <span
                key={i}
                style={{
                  color:
                    t.type === "val"
                      ? "var(--accent)"
                      : SYNTAX[t.type as keyof typeof SYNTAX] ?? SYNTAX.plain,
                }}
              >
                {t.text}
              </span>
            )
          )}
        </pre>
      </div>
    </div>
  );
}

function Hero() {
  return (
    <section
      id="hero"
      className="relative flex min-h-[90vh] flex-col items-center justify-center overflow-hidden px-8 pb-16 pt-20 text-center"
    >
      {/* Repeating grid: two linear gradients + var(--border) — not a single Tailwind utility */}
      <div
        className="pointer-events-none absolute inset-0 opacity-30"
        style={{
          backgroundImage:
            "linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }}
      />
      {/* Tailwind cannot express this radial gradient — kept as inline style */}
      <div
        className="pointer-events-none absolute left-1/2 top-[20%] h-[300px] w-[600px] -translate-x-1/2"
        style={{
          background:
            "radial-gradient(ellipse,rgba(0,229,160,0.13) 0%,transparent 70%)",
        }}
      />
      {/* Hero chip: exact rgba alpha on accent — kept inline to match previous design */}
      <div
        className="relative z-[1] mb-8 inline-flex items-center gap-2 rounded-full px-[18px] py-1.5 font-[family-name:JetBrains_Mono,monospace] text-[0.8rem] text-(--accent)"
        style={{
          background: "rgba(0,229,160,0.08)",
          border: "1px solid rgba(0,229,160,0.25)",
        }}
      >
        <span className="size-[7px] rounded-full bg-(--accent) [animation:pulse_2s_infinite]" />
        Open-source · RAG Engine for Developers
      </div>

      <h1 className="relative z-[1] max-w-[820px] text-[clamp(2.4rem,5vw,4.2rem)] font-semibold leading-[1.12] tracking-[-1.5px] text-(--foreground)">
        Build RAG apps that{" "}
        <span className="bg-gradient-to-r from-(--accent) to-(--blue) bg-clip-text text-transparent">
          actually understand
        </span>{" "}
        your data.
      </h1>

      <p className="relative z-[1] mx-auto mt-6 max-w-[540px] text-[1.1rem] font-light leading-[1.7] text-(--muted)">
        ChatVector is a high-performance retrieval-augmented generation engine —
        ingest any document, retrieve semantically, and get LLM-powered answers
        in minutes.
      </p>

      <div className="relative z-[1] mt-10 flex flex-wrap justify-center gap-4">
        <a
          href={GITHUB_REPO}
          className="flex cursor-pointer items-center gap-2 rounded-lg border-none bg-(--accent) px-7 py-3 text-[0.95rem] font-semibold text-black no-underline transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(0,229,160,0.25)]"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="currentColor"
          >
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.44 9.8 8.2 11.38.6.11.82-.26.82-.57v-2c-3.34.72-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.09-.74.08-.73.08-.73 1.21.08 1.84 1.24 1.84 1.24 1.07 1.83 2.81 1.3 3.5 1 .11-.78.42-1.3.76-1.6-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.12-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 3-.4c1.02 0 2.04.14 3 .4 2.28-1.55 3.29-1.23 3.29-1.23.66 1.66.24 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.63-5.48 5.92.43.37.81 1.1.81 2.22v3.29c0 .32.21.69.82.57C20.56 21.8 24 17.3 24 12c0-6.63-5.37-12-12-12z" />
          </svg>
          View on GitHub
        </a>
        <Link
          href="/chat"
          className="flex cursor-pointer items-center gap-2 rounded-lg border border-(--border) bg-transparent px-7 py-3 text-[0.95rem] font-medium text-(--foreground) no-underline transition-all duration-200 hover:border-[rgb(61,69,85)] hover:bg-(--surface)"
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

function PipelineStep({
  num,
  title,
  desc,
}: {
  num: string;
  title: string;
  desc: string;
}) {
  return (
    <div className="flex items-start gap-3.5 border-b border-(--border) py-3.5">
      {/* Step index badge: precise accent translucency */}
      <div
        className="flex size-7 shrink-0 items-center justify-center rounded-md border font-[family-name:JetBrains_Mono,monospace] text-xs font-bold text-(--accent)"
        style={{
          background: "rgba(0,229,160,0.1)",
          borderColor: "rgba(0,229,160,0.2)",
        }}
      >
        {num}
      </div>
      <div>
        <h4 className="mb-0.5 text-[0.9rem] font-medium text-(--foreground)">
          {title}
        </h4>
        <p className="m-0 text-[0.82rem] text-(--muted)">{desc}</p>
      </div>
    </div>
  );
}

function WhatIs() {
  const steps = [
    {
      num: "01",
      title: "Ingest",
      desc: "Load PDFs, HTML, text files. Auto-chunked and embedded.",
    },
    {
      num: "02",
      title: "Index",
      desc: "FAISS, Chroma, or your custom vector store. Your choice.",
    },
    {
      num: "03",
      title: "Retrieve",
      desc: "Semantic search with MMR re-ranking for diversity.",
    },
    {
      num: "04",
      title: "Generate",
      desc: "LLM answer grounded in retrieved context. Cited.",
    },
  ];
  return (
    <section id="about" className="bg-(--background) px-8 py-24">
      <div className="mx-auto max-w-[1100px]">
        <p className="mb-4 font-[family-name:JetBrains_Mono,monospace] text-[0.78rem] uppercase tracking-[2px] text-(--accent)">
          {"// what is chatvector"}
        </p>
        <h2 className="mb-5 text-[clamp(1.8rem,3.5vw,2.8rem)] font-semibold leading-tight tracking-[-0.8px] text-(--foreground)">
          RAG that&apos;s sharp, fast,
          <br />
          and open source.
        </h2>
        <p className="max-w-[560px] text-[1.05rem] font-light leading-[1.7] text-(--muted)">
          ChatVector handles the entire retrieval pipeline — from raw documents
          to grounded LLM responses — so you can focus on building, not
          plumbing.
        </p>

        <div className="mt-12 grid grid-cols-1 items-center gap-12 md:grid-cols-2 md:gap-12">
          <div>
            <p className="mb-5 text-[0.95rem] leading-[1.8] text-(--muted)">
              Most RAG implementations are fragile, slow, or locked into a
              vendor. ChatVector is different — a clean, composable engine built
              for developers who want full control.
            </p>
            <p className="text-[0.95rem] leading-[1.8] text-(--muted)">
              Swap your vector store, your LLM, or your chunking strategy
              without rewriting your app. Built on battle-tested primitives.
              Runs anywhere Python runs.
            </p>
          </div>
          <div className="rounded-xl border border-(--border) bg-(--surface) p-6">
            {steps.map((s) => (
              <PipelineStep key={s.num} {...s} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

const FEATURES = [
  {
    icon: "⬆",
    color: "var(--accent)",
    bg: "rgba(0,229,160,0.1)",
    title: "Multi-format ingestion",
    desc: "PDF, Markdown, HTML, DOCX, plain text. Drop a folder and go.",
    tag: "ingestion",
  },
  {
    icon: "🔍",
    color: "var(--blue)",
    bg: "rgba(0,128,255,0.1)",
    title: "Semantic retrieval",
    desc: "Dense vector search with optional MMR re-ranking for diverse, accurate hits.",
    tag: "retrieval",
  },
  {
    icon: "⚡",
    color: "rgb(168, 85, 247)",
    bg: "rgba(168,85,247,0.1)",
    title: "LLM-powered answers",
    desc: "Works with Mistral, LLaMA, GPT-4, Claude — any OpenAI-compatible endpoint.",
    tag: "generation",
  },
  {
    icon: "</>",
    color: "rgb(251, 191, 36)",
    bg: "rgba(251,191,36,0.1)",
    title: "Open source, self-hosted",
    desc: "MIT licensed. No cloud dependency. Run on your laptop or your infra.",
    tag: "open-source",
  },
  {
    icon: "✓",
    color: "rgb(16, 185, 129)",
    bg: "rgba(16,185,129,0.1)",
    title: "Cited responses",
    desc: "Every answer links back to source chunks. No hallucinations, full traceability.",
    tag: "trust",
  },
  {
    icon: "⬡",
    color: "rgb(239, 68, 68)",
    bg: "rgba(239,68,68,0.1)",
    title: "Pluggable vector stores",
    desc: "FAISS, ChromaDB, Pinecone, Weaviate. Swap with one config line.",
    tag: "modular",
  },
];

function FeatureCard({
  icon,
  color,
  bg,
  title,
  desc,
  tag,
}: {
  icon: string;
  color: string;
  bg: string;
  title: string;
  desc: string;
  tag: string;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`cursor-default rounded-xl border p-6 transition-all duration-[250ms] bg-(--background) ${
        hovered
          ? "-translate-y-[3px] border-[rgb(61,69,85)]"
          : "translate-y-0 border-(--border)"
      }`}
    >
      {/* Icon tile fill and glyph color come from FEATURES[] (per-card palette) */}
      <div
        className="mb-4 flex size-10 items-center justify-center rounded-[10px] text-[1.1rem]"
        style={{ background: bg }}
      >
        <span style={{ color }}>{icon}</span>
      </div>
      <h3 className="mb-2 text-base font-medium text-(--foreground)">
        {title}
      </h3>
      <p className="m-0 text-[0.85rem] leading-snug text-(--muted)">{desc}</p>
      <div className="mt-3 inline-block rounded border border-[color-mix(in_srgb,var(--blue)_20%,transparent)] bg-[color-mix(in_srgb,var(--blue)_10%,transparent)] px-2.5 py-0.5 font-[family-name:JetBrains_Mono,monospace] text-[0.72rem] text-(--blue)">
        {tag}
      </div>
    </div>
  );
}

function Features() {
  return (
    <section id="features" className="bg-(--surface) px-8 py-24">
      <div className="mx-auto max-w-[1100px]">
        <p className="mb-4 font-[family-name:JetBrains_Mono,monospace] text-[0.78rem] uppercase tracking-[2px] text-(--accent)">
          {"// capabilities"}
        </p>
        <h2 className="mb-12 text-[clamp(1.8rem,3.5vw,2.8rem)] font-semibold leading-tight tracking-[-0.8px] text-(--foreground)">
          Everything you need.
          <br />
          Nothing you don&apos;t.
        </h2>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-6">
          {FEATURES.map((f) => (
            <FeatureCard key={f.title} {...f} />
          ))}
        </div>
      </div>
    </section>
  );
}

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

function Developers() {
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
    <section id="developers" className="bg-(--background) px-8 py-24">
      <div className="mx-auto max-w-[1100px]">
        <p className="mb-4 font-[family-name:JetBrains_Mono,monospace] text-[0.78rem] uppercase tracking-[2px] text-(--accent)">
          {"// built for developers"}
        </p>
        <h2 className="mb-4 text-[clamp(1.8rem,3.5vw,2.8rem)] font-semibold leading-tight tracking-[-0.8px] text-(--foreground)">
          Designed for people who
          <br />
          read the source code.
        </h2>
        <p className="mb-12 max-w-[540px] text-[1.05rem] font-light leading-[1.7] text-(--muted)">
          No drag-and-drop. No &quot;AI magic&quot;. Just clean Python APIs,
          sensible defaults, and full control when you need it.
        </p>

        <div className="grid grid-cols-1 items-center gap-12 md:grid-cols-2 md:gap-12">
          <div className="flex flex-col gap-4">
            {DEV_POINTS.map((p) => (
              <div
                key={p.title}
                className="flex items-start gap-3.5 rounded-r-[10px] border border-(--border) border-l-[3px] border-l-(--accent) bg-(--surface) py-4 pl-5 pr-4"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  className="mt-0.5 shrink-0 text-(--accent)"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <div>
                  <h4 className="mb-0.5 text-[0.92rem] font-medium text-(--foreground)">
                    {p.title}
                  </h4>
                  <p className="m-0 text-[0.82rem] text-(--muted)">{p.desc}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="overflow-hidden rounded-xl border border-(--border) bg-(--surface)">
            <div className="flex items-center gap-2 border-b border-(--border) bg-[rgb(24,28,34)] px-4 py-3">
              <div className="size-2.5 rounded-full bg-[rgb(255,95,87)]" />
              <div className="size-2.5 rounded-full bg-[rgb(254,188,46)]" />
              <div className="size-2.5 rounded-full bg-[rgb(40,200,64)]" />
              <span className="ml-auto font-[family-name:JetBrains_Mono,monospace] text-xs text-(--muted)">
                custom_pipeline.py
              </span>
            </div>
            {/* Per-span colors mirror the sample Python highlighter */}
            <pre className="m-0 overflow-x-auto px-6 py-5 font-[family-name:JetBrains_Mono,monospace] text-[0.82rem] leading-[1.75]">
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

const FOOTER_LINKS: { label: string; href: string; external?: boolean }[] = [
  { label: "GitHub", href: GITHUB_REPO, external: true },
  { label: "Docs", href: "#" },
  { label: "Roadmap", href: "#" },
  { label: "Issues", href: `${GITHUB_REPO}/issues`, external: true },
  {
    label: "License (MIT)",
    href: `${GITHUB_REPO}/blob/main/LICENSE`,
    external: true,
  },
];

function Footer() {
  return (
    <footer className="border-t border-(--border) px-8 py-10">
      <div className="mx-auto flex max-w-[1100px] flex-wrap items-center justify-between gap-6">
        <div className="font-[family-name:JetBrains_Mono,monospace] text-base font-bold text-(--accent)">
          ChatVector
        </div>
        <div className="flex flex-wrap gap-8">
          {FOOTER_LINKS.map(({ label, href, external }) => (
            <a
              key={label}
              href={href}
              {...(external
                ? { target: "_blank", rel: "noopener noreferrer" }
                : {})}
              className="text-[0.88rem] text-(--muted) no-underline transition-colors duration-200 hover:text-(--foreground)"
            >
              {label}
            </a>
          ))}
        </div>
        <div className="text-[0.82rem] text-[rgb(61,69,85)]">
          © 2026 ChatVector · Open Source · MIT
        </div>
      </div>
    </footer>
  );
}

export default function Home() {
  return (
    <div className="min-h-screen bg-(--background) font-[family-name:DM_Sans,sans-serif] text-(--foreground)">
      <Hero />
      <WhatIs />
      <Features />
      <Developers />
      <Footer />
    </div>
  );
}

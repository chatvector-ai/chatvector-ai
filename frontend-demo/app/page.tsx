"use client";

import Link from "next/link";
import { useState } from "react";

const GITHUB_REPO = "https://github.com/chatvector-ai/chatvector-ai";

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

  const colors: Record<string, string> = {
    kw: "#ff7b72",
    fn: "#79c0ff",
    str: "#a5d6ff",
    cm: "#8b949e",
    val: "#00e5a0",
    plain: "#c9d1d9",
  };

  return (
    <div style={{ maxWidth: 700, width: "100%", marginTop: "3rem" }}>
      <div
        style={{
          background: "#111418",
          border: "1px solid #1e2530",
          borderRadius: 12,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "12px 16px",
            borderBottom: "1px solid #1e2530",
            background: "#181c22",
          }}
        >
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#ff5f57",
            }}
          />
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#febc2e",
            }}
          />
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#28c840",
            }}
          />
          <span
            style={{
              marginLeft: "auto",
              fontFamily: "JetBrains Mono, monospace",
              fontSize: "0.75rem",
              color: "#6b7685",
            }}
          >
            quickstart.py
          </span>
        </div>
        <pre
          style={{
            padding: "1.25rem 1.5rem",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: "0.82rem",
            lineHeight: 1.75,
            overflowX: "auto",
            margin: 0,
          }}
        >
          {lines.map((t, i) =>
            t.type === "br" ? (
              <br key={i} />
            ) : (
              <span key={i} style={{ color: colors[t.type] || "#c9d1d9" }}>
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
      style={{
        minHeight: "90vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: "5rem 2rem 4rem",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(#1e2530 1px,transparent 1px),linear-gradient(90deg,#1e2530 1px,transparent 1px)",
          backgroundSize: "60px 60px",
          opacity: 0.3,
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: "20%",
          left: "50%",
          transform: "translateX(-50%)",
          width: 600,
          height: 300,
          pointerEvents: "none",
          background:
            "radial-gradient(ellipse,rgba(0,229,160,0.13) 0%,transparent 70%)",
        }}
      />
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          background: "rgba(0,229,160,0.08)",
          border: "1px solid rgba(0,229,160,0.25)",
          color: "#00e5a0",
          padding: "6px 18px",
          borderRadius: 999,
          fontSize: "0.8rem",
          fontFamily: "JetBrains Mono, monospace",
          marginBottom: "2rem",
          position: "relative",
          zIndex: 1,
        }}
      >
        <span
          style={{
            width: 7,
            height: 7,
            background: "#00e5a0",
            borderRadius: "50%",
            animation: "pulse 2s infinite",
          }}
        />
        Open-source · RAG Engine for Developers
      </div>

      <h1
        style={{
          fontSize: "clamp(2.4rem,5vw,4.2rem)",
          fontWeight: 600,
          lineHeight: 1.12,
          letterSpacing: "-1.5px",
          maxWidth: 820,
          position: "relative",
          zIndex: 1,
          color: "#e8edf5",
        }}
      >
        Build RAG apps that{" "}
        <span
          style={{
            color: "transparent",
            background: "linear-gradient(90deg,#00e5a0,#0080ff)",
            WebkitBackgroundClip: "text",
            backgroundClip: "text",
          }}
        >
          actually understand
        </span>{" "}
        your data.
      </h1>

      <p
        style={{
          color: "#6b7685",
          fontSize: "1.1rem",
          maxWidth: 540,
          margin: "1.5rem auto 0",
          fontWeight: 300,
          lineHeight: 1.7,
          position: "relative",
          zIndex: 1,
        }}
      >
        ChatVector is a high-performance retrieval-augmented generation engine —
        ingest any document, retrieve semantically, and get LLM-powered answers
        in minutes.
      </p>

      <div
        style={{
          display: "flex",
          gap: "1rem",
          marginTop: "2.5rem",
          justifyContent: "center",
          flexWrap: "wrap",
          position: "relative",
          zIndex: 1,
        }}
      >
        <a
          href={GITHUB_REPO}
          style={{
            background: "#00e5a0",
            color: "#000",
            padding: "12px 28px",
            borderRadius: 8,
            fontSize: "0.95rem",
            fontWeight: 600,
            border: "none",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 8,
            textDecoration: "none",
            transition: "all .2s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.transform =
              "translateY(-2px)";
            (e.currentTarget as HTMLElement).style.boxShadow =
              "0 8px 24px rgba(0,229,160,0.25)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.transform = "translateY(0)";
            (e.currentTarget as HTMLElement).style.boxShadow = "none";
          }}
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
          style={{
            background: "transparent",
            color: "#e8edf5",
            padding: "12px 28px",
            borderRadius: 8,
            fontSize: "0.95rem",
            fontWeight: 500,
            border: "1px solid #1e2530",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 8,
            textDecoration: "none",
            transition: "all .2s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "#3d4555";
            e.currentTarget.style.background = "#111418";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "#1e2530";
            e.currentTarget.style.background = "transparent";
          }}
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
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 14,
        padding: "14px 0",
        borderBottom: "1px solid #1e2530",
      }}
    >
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: "0.75rem",
          color: "#00e5a0",
          background: "rgba(0,229,160,0.1)",
          border: "1px solid rgba(0,229,160,0.2)",
          width: 28,
          height: 28,
          borderRadius: 6,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          fontWeight: 700,
        }}
      >
        {num}
      </div>
      <div>
        <h4
          style={{
            fontSize: "0.9rem",
            fontWeight: 500,
            marginBottom: 3,
            color: "#e8edf5",
          }}
        >
          {title}
        </h4>
        <p style={{ fontSize: "0.82rem", color: "#6b7685", margin: 0 }}>
          {desc}
        </p>
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
    <section id="about" style={{ padding: "6rem 2rem", background: "#0a0c10" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <p
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: "0.78rem",
            color: "#00e5a0",
            letterSpacing: "2px",
            textTransform: "uppercase",
            marginBottom: "1rem",
          }}
        >
          {"// what is chatvector"}
        </p>
        <h2
          style={{
            fontSize: "clamp(1.8rem,3.5vw,2.8rem)",
            fontWeight: 600,
            letterSpacing: "-0.8px",
            lineHeight: 1.2,
            marginBottom: "1.2rem",
            color: "#e8edf5",
          }}
        >
          RAG that&apos;s sharp, fast,
          <br />
          and open source.
        </h2>
        <p
          style={{
            color: "#6b7685",
            fontSize: "1.05rem",
            fontWeight: 300,
            maxWidth: 560,
            lineHeight: 1.7,
          }}
        >
          ChatVector handles the entire retrieval pipeline — from raw documents
          to grounded LLM responses — so you can focus on building, not
          plumbing.
        </p>

        <div
          className="grid grid-cols-1 gap-12 md:grid-cols-2 md:gap-12"
          style={{
            alignItems: "center",
            marginTop: "3rem",
          }}
        >
          <div>
            <p
              style={{
                color: "#6b7685",
                fontSize: "0.95rem",
                lineHeight: 1.8,
                marginBottom: "1.2rem",
              }}
            >
              Most RAG implementations are fragile, slow, or locked into a
              vendor. ChatVector is different — a clean, composable engine built
              for developers who want full control.
            </p>
            <p
              style={{ color: "#6b7685", fontSize: "0.95rem", lineHeight: 1.8 }}
            >
              Swap your vector store, your LLM, or your chunking strategy
              without rewriting your app. Built on battle-tested primitives.
              Runs anywhere Python runs.
            </p>
          </div>
          <div
            style={{
              background: "#111418",
              border: "1px solid #1e2530",
              borderRadius: 12,
              padding: "1.5rem",
            }}
          >
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
    color: "#00e5a0",
    bg: "rgba(0,229,160,0.1)",
    title: "Multi-format ingestion",
    desc: "PDF, Markdown, HTML, DOCX, plain text. Drop a folder and go.",
    tag: "ingestion",
  },
  {
    icon: "🔍",
    color: "#0080ff",
    bg: "rgba(0,128,255,0.1)",
    title: "Semantic retrieval",
    desc: "Dense vector search with optional MMR re-ranking for diverse, accurate hits.",
    tag: "retrieval",
  },
  {
    icon: "⚡",
    color: "#a855f7",
    bg: "rgba(168,85,247,0.1)",
    title: "LLM-powered answers",
    desc: "Works with Mistral, LLaMA, GPT-4, Claude — any OpenAI-compatible endpoint.",
    tag: "generation",
  },
  {
    icon: "</>",
    color: "#fbbf24",
    bg: "rgba(251,191,36,0.1)",
    title: "Open source, self-hosted",
    desc: "MIT licensed. No cloud dependency. Run on your laptop or your infra.",
    tag: "open-source",
  },
  {
    icon: "✓",
    color: "#10b981",
    bg: "rgba(16,185,129,0.1)",
    title: "Cited responses",
    desc: "Every answer links back to source chunks. No hallucinations, full traceability.",
    tag: "trust",
  },
  {
    icon: "⬡",
    color: "#ef4444",
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
      style={{
        background: "#0a0c10",
        border: `1px solid ${hovered ? "#3d4555" : "#1e2530"}`,
        borderRadius: 12,
        padding: "1.5rem",
        transform: hovered ? "translateY(-3px)" : "none",
        transition: "all .25s",
        cursor: "default",
      }}
    >
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: 10,
          background: bg,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "1.1rem",
          marginBottom: "1rem",
        }}
      >
        <span style={{ color }}>{icon}</span>
      </div>
      <h3
        style={{
          fontSize: "1rem",
          fontWeight: 500,
          marginBottom: "0.5rem",
          color: "#e8edf5",
        }}
      >
        {title}
      </h3>
      <p
        style={{ fontSize: "0.85rem", color: "#6b7685", lineHeight: 1.6, margin: 0 }}
      >
        {desc}
      </p>
      <div
        style={{
          display: "inline-block",
          background: "rgba(0,128,255,0.1)",
          border: "1px solid rgba(0,128,255,0.2)",
          color: "#0080ff",
          padding: "2px 10px",
          borderRadius: 4,
          fontSize: "0.72rem",
          fontFamily: "JetBrains Mono, monospace",
          marginTop: "0.75rem",
        }}
      >
        {tag}
      </div>
    </div>
  );
}

function Features() {
  return (
    <section
      id="features"
      style={{ padding: "6rem 2rem", background: "#111418" }}
    >
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <p
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: "0.78rem",
            color: "#00e5a0",
            letterSpacing: "2px",
            textTransform: "uppercase",
            marginBottom: "1rem",
          }}
        >
          {"// capabilities"}
        </p>
        <h2
          style={{
            fontSize: "clamp(1.8rem,3.5vw,2.8rem)",
            fontWeight: 600,
            letterSpacing: "-0.8px",
            lineHeight: 1.2,
            marginBottom: "3rem",
            color: "#e8edf5",
          }}
        >
          Everything you need.
          <br />
          Nothing you don&apos;t.
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))",
            gap: "1.5rem",
          }}
        >
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
    { parts: [{ c: "#8b949e", t: "# Swap components without rewriting" }] },
    {
      parts: [
        { c: "#c9d1d9", t: "cv = " },
        { c: "#79c0ff", t: "ChatVector" },
        { c: "#c9d1d9", t: "(" },
      ],
    },
    {
      parts: [
        { c: "#c9d1d9", t: "  embedder=" },
        { c: "#79c0ff", t: "HuggingFaceEmbedder" },
        { c: "#c9d1d9", t: "(" },
      ],
    },
    {
      parts: [
        { c: "#c9d1d9", t: "    model=" },
        { c: "#a5d6ff", t: '"BAAI/bge-small-en"' },
      ],
    },
    { parts: [{ c: "#c9d1d9", t: "  )," }] },
    {
      parts: [
        { c: "#c9d1d9", t: "  store=" },
        { c: "#79c0ff", t: "ChromaStore" },
        { c: "#c9d1d9", t: "(path=" },
        { c: "#a5d6ff", t: '"./db"' },
        { c: "#c9d1d9", t: ")," },
      ],
    },
    {
      parts: [
        { c: "#c9d1d9", t: "  llm=" },
        { c: "#79c0ff", t: "OllamaLLM" },
        { c: "#c9d1d9", t: "(model=" },
        { c: "#a5d6ff", t: '"llama3"' },
        { c: "#c9d1d9", t: ")," },
      ],
    },
    {
      parts: [
        { c: "#c9d1d9", t: "  retriever=" },
        { c: "#79c0ff", t: "MMRRetriever" },
        { c: "#c9d1d9", t: "(k=" },
        { c: "#00e5a0", t: "6" },
        { c: "#c9d1d9", t: ")," },
      ],
    },
    { parts: [{ c: "#c9d1d9", t: ")" }] },
    { parts: [] },
    { parts: [{ c: "#8b949e", t: "# Full control, clean API" }] },
    {
      parts: [
        { c: "#c9d1d9", t: "docs = cv." },
        { c: "#79c0ff", t: "retrieve" },
        { c: "#c9d1d9", t: "(query, top_k=" },
        { c: "#00e5a0", t: "8" },
        { c: "#c9d1d9", t: ")" },
      ],
    },
    {
      parts: [
        { c: "#c9d1d9", t: "answer = cv." },
        { c: "#79c0ff", t: "generate" },
        { c: "#c9d1d9", t: "(query, docs)" },
      ],
    },
  ];

  return (
    <section
      id="developers"
      style={{ padding: "6rem 2rem", background: "#0a0c10" }}
    >
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <p
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: "0.78rem",
            color: "#00e5a0",
            letterSpacing: "2px",
            textTransform: "uppercase",
            marginBottom: "1rem",
          }}
        >
          {"// built for developers"}
        </p>
        <h2
          style={{
            fontSize: "clamp(1.8rem,3.5vw,2.8rem)",
            fontWeight: 600,
            letterSpacing: "-0.8px",
            lineHeight: 1.2,
            marginBottom: "1rem",
            color: "#e8edf5",
          }}
        >
          Designed for people who
          <br />
          read the source code.
        </h2>
        <p
          style={{
            color: "#6b7685",
            fontSize: "1.05rem",
            fontWeight: 300,
            maxWidth: 540,
            lineHeight: 1.7,
            marginBottom: "3rem",
          }}
        >
          No drag-and-drop. No &quot;AI magic&quot;. Just clean Python APIs,
          sensible defaults, and full control when you need it.
        </p>

        <div
          className="grid grid-cols-1 gap-12 md:grid-cols-2 md:gap-12"
          style={{
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            {DEV_POINTS.map((p) => (
              <div
                key={p.title}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 14,
                  padding: "1rem 1.2rem",
                  background: "#111418",
                  border: "1px solid #1e2530",
                  borderLeft: "3px solid #00e5a0",
                  borderRadius: "0 10px 10px 0",
                }}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="#00e5a0"
                  strokeWidth="2.5"
                  style={{ flexShrink: 0, marginTop: 3 }}
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <div>
                  <h4
                    style={{
                      fontSize: "0.92rem",
                      fontWeight: 500,
                      marginBottom: 3,
                      color: "#e8edf5",
                    }}
                  >
                    {p.title}
                  </h4>
                  <p style={{ fontSize: "0.82rem", color: "#6b7685", margin: 0 }}>
                    {p.desc}
                  </p>
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              background: "#111418",
              border: "1px solid #1e2530",
              borderRadius: 12,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "12px 16px",
                borderBottom: "1px solid #1e2530",
                background: "#181c22",
              }}
            >
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: "#ff5f57",
                }}
              />
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: "#febc2e",
                }}
              />
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: "#28c840",
                }}
              />
              <span
                style={{
                  marginLeft: "auto",
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: "0.75rem",
                  color: "#6b7685",
                }}
              >
                custom_pipeline.py
              </span>
            </div>
            <pre
              style={{
                padding: "1.25rem 1.5rem",
                fontFamily: "JetBrains Mono, monospace",
                fontSize: "0.82rem",
                lineHeight: 1.75,
                overflowX: "auto",
                margin: 0,
              }}
            >
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
    <footer style={{ borderTop: "1px solid #1e2530", padding: "2.5rem 2rem" }}>
      <div
        style={{
          maxWidth: 1100,
          margin: "0 auto",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "1.5rem",
        }}
      >
        <div
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: "1rem",
            fontWeight: 700,
            color: "#00e5a0",
          }}
        >
          ChatVector
        </div>
        <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
          {FOOTER_LINKS.map(({ label, href, external }) => (
            <a
              key={label}
              href={href}
              {...(external
                ? { target: "_blank", rel: "noopener noreferrer" }
                : {})}
              style={{
                color: "#6b7685",
                textDecoration: "none",
                fontSize: "0.88rem",
                transition: "color .2s",
              }}
              onMouseEnter={(e) =>
                ((e.target as HTMLElement).style.color = "#e8edf5")
              }
              onMouseLeave={(e) =>
                ((e.target as HTMLElement).style.color = "#6b7685")
              }
            >
              {label}
            </a>
          ))}
        </div>
        <div style={{ color: "#3d4555", fontSize: "0.82rem" }}>
          © 2026 ChatVector · Open Source · MIT
        </div>
      </div>
    </footer>
  );
}

export default function Home() {
  return (
    <div
      style={{
        background: "#0a0c10",
        color: "#e8edf5",
        fontFamily: "'DM Sans', sans-serif",
        minHeight: "100vh",
      }}
    >
      <Hero />
      <WhatIs />
      <Features />
      <Developers />
      <Footer />
    </div>
  );
}
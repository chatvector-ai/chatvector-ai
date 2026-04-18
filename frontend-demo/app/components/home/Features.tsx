const FEATURES = [
  {
    icon: "⬆",
    color: "var(--accent)",
    bg: "color-mix(in srgb, var(--accent) 10%, transparent)",
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
    desc: "Powered by Google Gemini. LLM answers grounded in your document context — not hallucinated from training data.",
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
    title: "pgvector / Supabase storage",
    desc: "Document embeddings stored in pgvector via Supabase. Reliable, SQL-native, no separate vector DB to manage.",
    tag: "storage",
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
  // Pure CSS hover via group — no JS state needed
  return (
    <div className="group cursor-default rounded-xl border border-border bg-background p-6 transition-all duration-[250ms] hover:-translate-y-[3px] hover:border-[rgb(61,69,85)]">
      {/* Icon tile fill and glyph color are per-card (feature palette, not design tokens) */}
      <div
        className="mb-4 flex size-10 items-center justify-center rounded-[10px] text-[1.1rem]"
        style={{ background: bg }}
      >
        <span style={{ color }}>{icon}</span>
      </div>
      <h3 className="mb-2 text-lg font-medium text-foreground">{title}</h3>
      <p className="m-0 text-lg leading-relaxed text-muted">{desc}</p>
      {/* Tag badge: sub-20% alpha on blue — kept inline for exact rgba match */}
      <div
        className="mt-3 inline-block rounded px-2.5 py-0.5 font-mono text-sm text-blue"
        style={{
          background: "rgba(0,128,255,0.1)",
          border: "1px solid rgba(0,128,255,0.2)",
        }}
      >
        {tag}
      </div>
    </div>
  );
}

export default function Features() {
  return (
    <section id="features" className="bg-surface px-8 py-24">
      <div className="mx-auto max-w-[1100px]">
        <p className="mb-4 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
          {"// capabilities"}
        </p>
        <h2 className="mb-12 text-[clamp(1.8rem,3.5vw,2.8rem)] font-semibold leading-tight tracking-[-0.8px] text-foreground">
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

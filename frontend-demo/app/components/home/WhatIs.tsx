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
    <div className="flex items-start gap-3.5 border-b border-border py-3.5">
      {/* Step badge: sub-20% alpha on accent — kept inline for exact rgba match */}
      <div
        className="flex size-7 shrink-0 items-center justify-center rounded-md border font-mono text-xs font-bold text-accent"
        style={{
          background: "color-mix(in srgb, var(--accent) 10%, transparent)",
          borderColor: "color-mix(in srgb, var(--accent) 20%, transparent)",
        }}
      >
        {num}
      </div>
      <div>
        <h3 className="mb-0.5 text-base font-medium text-foreground">
          {title}
        </h3>
        <p className="m-0 text-base leading-relaxed text-muted">{desc}</p>
      </div>
    </div>
  );
}

export default function WhatIs() {
  const steps = [
    {
      num: "01",
      title: "Ingest",
      desc: "Load PDFs, HTML, text files. Auto-chunked and embedded.",
    },
    {
      num: "02",
      title: "Index",
      desc: "Embeddings stored in pgvector via Supabase. Fast, reliable, SQL-native.",
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
    <section id="about" className="bg-background px-8 py-24">
      <div className="mx-auto max-w-[1100px]">
        <p className="mb-4 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
          {"// what is chatvector"}
        </p>
        <h2 className="mb-5 text-[clamp(1.8rem,3.5vw,2.8rem)] font-semibold leading-tight tracking-[-0.8px] text-foreground">
          RAG that&apos;s sharp, fast,
          <br />
          and open source.
        </h2>
        <p className="max-w-[560px] text-lg font-light leading-relaxed text-muted">
          ChatVector handles the entire retrieval pipeline — from raw documents
          to grounded LLM responses — so you can focus on building, not
          plumbing.
        </p>

        <div className="mt-12 grid grid-cols-1 items-center gap-12 md:grid-cols-2">
          <div>
            <p className="mb-5 text-lg leading-relaxed text-muted">
              Most RAG implementations are fragile, slow, or locked into a
              vendor. ChatVector is different — a deployable service you host
              yourself, with a clean HTTP API and no cloud dependency.
            </p>
            <p className="text-lg leading-relaxed text-muted">
              Spin up the Docker container, point the SDK at it, and start
              querying your documents in minutes. Built on FastAPI and pgvector.
              Runs anywhere Docker runs.
            </p>
          </div>
          <div className="rounded-xl border border-border bg-surface p-6">
            {steps.map((s) => (
              <PipelineStep key={s.num} {...s} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

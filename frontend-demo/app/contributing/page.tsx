export default function ArchitecturePage() {
  return (
    <div className="max-w-[720px] mx-auto px-4 py-10">

      {/* Hero */}
      <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-2">
        Internals
      </p>
      <h1 className="text-3xl font-bold mb-4 text-foreground">
        Architecture
      </h1>
      <p className="text-foreground text-[1rem] leading-[1.8] mb-10">
        ChatVector is built as a production-ready RAG (Retrieval-Augmented Generation) engine —
        not a general-purpose framework. This page summarises how the system is structured
        internally so contributors and evaluators can orient quickly.
      </p>

      {/* 01 — System Design */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        01 — System Design
      </h2>
      <h3 className="text-lg font-semibold text-foreground mb-3">
        Layered Architecture Overview
      </h3>
      <p className="text-foreground text-[1rem] leading-[1.8] mb-4">
        The stack is deliberately layered so each concern is isolated. From top to bottom:
      </p>
      <pre className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] p-5 overflow-x-auto mb-10 text-foreground leading-[1.7]">{`┌─────────────────────────────────┐
│        API Layer (FastAPI)      │  ← HTTP endpoints, validation
├─────────────────────────────────┤
│     Ingestion / Query Logic     │  ← chunking, embedding, retrieval
├─────────────────────────────────┤
│   Database Strategy (Adapter)   │  ← SQLAlchemy  /  Supabase
├─────────────────────────────────┤
│     Vector Store (pgvector)     │  ← similarity search in Postgres
└─────────────────────────────────┘`}</pre>

      {/* 02 — Database */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        02 — Database
      </h2>
      <h3 className="text-lg font-semibold text-foreground mb-3">
        Database Strategy Pattern
      </h3>
      <p className="text-foreground text-[1rem] leading-[1.8] mb-6">
        ChatVector uses a <em>Strategy Pattern</em> for database access. The application code
        never talks to a specific database driver directly — it calls a common interface backed
        by either <strong>SQLAlchemy</strong> (local / Docker) or{" "}
        <strong>Supabase</strong> (hosted production). Swapping backends requires only an
        environment variable change.
      </p>

      {/* Dev vs Prod table */}
      <div className="overflow-x-auto mb-10">
        <table className="w-full bg-surface border border-border rounded-xl text-[0.9rem] text-foreground">
          <thead>
            <tr>
              {["", "Development", "Production"].map((h) => (
                <th
                  key={h}
                  className="px-4 py-3 text-left border-b border-border font-semibold"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[
              ["Backend", "SQLAlchemy + Docker Postgres", "Supabase (managed Postgres)"],
              ["Vector store", "pgvector via Docker", "pgvector via Supabase"],
              ["Setup", "docker compose up", "Set SUPABASE_URL + SUPABASE_KEY"],
              ["Cost", "Free", "Supabase free tier / paid"],
              ["Best for", "Local dev & CI", "Deployed / shared environments"],
            ].map(([label, dev, prod]) => (
              <tr key={label}>
                <td className="px-4 py-3 border-b border-border font-mono text-[0.8rem] text-accent">
                  {label}
                </td>
                <td className="px-4 py-3 border-b border-border">{dev}</td>
                <td className="px-4 py-3 border-b border-border">{prod}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 03 — Retry Logic */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        03 — Reliability
      </h2>
      <h3 className="text-lg font-semibold text-foreground mb-3">
        Retry Logic
      </h3>
      <p className="text-foreground text-[1rem] leading-[1.8] mb-4">
        Database writes in the ingestion pipeline — particularly{" "}
        <code className="px-1 py-0.5 bg-surface border border-border rounded font-mono text-[0.85em]">
          insert_chunk
        </code>{" "}
        — use explicit retry logic with exponential back-off to handle transient failures.
        This is a blocking dependency for batch ingestion and validation features (see{" "}
        <a
          href="https://github.com/chatvector-ai/chatvector-ai/issues/44"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:text-accent/80"
        >
          #44
        </a>
        ).
      </p>
      <pre className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] p-5 overflow-x-auto mb-10 text-foreground leading-[1.7]">{`for attempt in range(MAX_RETRIES):
    try:
        insert_chunk(chunk)
        break
    except TransientDBError:
        wait(backoff(attempt))
        continue`}</pre>

      {/* 04 — Ingestion Queue */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        04 — Ingestion
      </h2>
      <h3 className="text-lg font-semibold text-foreground mb-3">
        Ingestion Queue
      </h3>
      <div className="bg-surface border border-border border-l-[3px] border-l-accent p-4 mb-10">
        <p className="text-foreground text-[1rem] leading-[1.8]">
          Documents are parsed, chunked, and embedded asynchronously via an{" "}
          <code className="px-1 py-0.5 bg-surface border border-border rounded font-mono text-[0.85em]">
            asyncio.Queue
          </code>{" "}
          with a background worker pool, token bucket rate limiter, exponential backoff with
          jitter, and a dead-letter queue for failed jobs. A Redis replacement is planned for
          Phase 2 to support higher-throughput batch processing at scale.
        </p>
      </div>

      {/* 05 — Vector Search */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        05 — Vector Search
      </h2>
      <h3 className="text-lg font-semibold text-foreground mb-3">
        Vector Search Design
      </h3>
      <p className="text-foreground text-[1rem] leading-[1.8] mb-4">
        Similarity search is handled by <strong>pgvector</strong> running inside Postgres — no
        separate vector database required. Embeddings are stored alongside document metadata in
        the same schema, keeping the operational footprint minimal.
      </p>
      <pre className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] p-5 overflow-x-auto mb-10 text-foreground leading-[1.7]">{`-- Schema overview (simplified)
chunks (
  id          UUID PRIMARY KEY,
  document_id UUID REFERENCES documents(id),
  content     TEXT,
  embedding   VECTOR(3072),  -- pgvector column
  created_at  TIMESTAMPTZ
)

-- Nearest-neighbour query
SELECT content
FROM   chunks
ORDER  BY embedding <-> $query_vector
LIMIT  $top_k;`}</pre>

      {/* 06 — Design Principles */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        06 — Philosophy
      </h2>
      <h3 className="text-lg font-semibold text-foreground mb-4">
        Design Principles
      </h3>
      <div className="space-y-3 mb-10">
        {[
          {
            title: "Opinionated over configurable",
            body: "One well-lit path for document Q&A rather than an n-dimensional framework.",
          },
          {
            title: "Batteries included",
            body: "Logging, testing, retry logic, and a clean API ship out of the box.",
          },
          {
            title: "Minimal operational surface",
            body: "pgvector in Postgres means one fewer service to run in production.",
          },
          {
            title: "Contributor-friendly",
            body: "Clear issue labels, a single docker compose command, and good-first-issue tags keep onboarding friction low.",
          },
        ].map(({ title, body }) => (
          <div
            key={title}
            className="bg-surface border border-border rounded-xl px-5 py-4"
          >
            <p className="font-semibold text-foreground text-[0.95rem] mb-1">{title}</p>
            <p className="text-foreground text-[0.92rem] leading-[1.7]">{body}</p>
          </div>
        ))}
      </div>

      {/* Footer */}
      <p className="text-foreground text-[1rem] leading-[1.8] border-t border-border pt-6">
        For full architecture details, see{" "}
        <a
          href="https://github.com/chatvector-ai/chatvector-ai/blob/main/ARCHITECTURE.md"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:text-accent/80"
        >
          ARCHITECTURE.md on GitHub
        </a>
        .
      </p>
    </div>
  );
}
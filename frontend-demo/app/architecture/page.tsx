import { DocLayout } from "@/app/components/DocLayout";
import { DocPageHeader } from "@/app/components/DocPageHeader";
import { Kicker } from "@/app/components/Kicker";

export default function ArchitecturePage() {
  return (
    <DocLayout>
      <DocPageHeader
        kicker="internals"
        title="Architecture"
        description="ChatVector is built as a production-ready RAG (Retrieval-Augmented Generation) engine — not a general-purpose framework. This page summarises how the system is structured internally so contributors and evaluators can orient quickly."
      />

      <div className="mt-10 space-y-10">
        <section>
          <Kicker variant="numbered" spacing="sm">
            01 — System Design
          </Kicker>
          <h2 className="mb-3 text-lg font-semibold text-foreground">
            Layered Architecture Overview
          </h2>
          <p className="mb-4 text-[1rem] leading-[1.8] text-foreground">
            The stack is deliberately layered so each concern is isolated. From top to bottom:
          </p>
          <pre className="mb-10 overflow-x-auto rounded-xl border border-border bg-surface p-5 font-mono text-[0.82rem] leading-[1.7] text-foreground">{`┌─────────────────────────────────┐
│        API Layer (FastAPI)      │  ← HTTP endpoints, validation
├─────────────────────────────────┤
│     Ingestion / Query Logic     │  ← chunking, embedding, retrieval
├─────────────────────────────────┤
│   Database Strategy (Adapter)   │  ← SQLAlchemy  /  Supabase
├─────────────────────────────────┤
│     Vector Store (pgvector)     │  ← similarity search in Postgres
└─────────────────────────────────┘`}</pre>
        </section>

        <section>
          <Kicker variant="numbered" spacing="sm">
            02 — Database
          </Kicker>
          <h2 className="mb-3 text-lg font-semibold text-foreground">
            Database Strategy Pattern
          </h2>
          <p className="mb-6 text-[1rem] leading-[1.8] text-foreground">
            ChatVector uses a <em>Strategy Pattern</em> for database access. The application code
            never talks to a specific database driver directly — it calls a common interface backed
            by either <strong>SQLAlchemy</strong> (local / Docker) or{" "}
            <strong>Supabase</strong> (hosted production). Swapping backends requires only an
            environment variable change.
          </p>

          <div className="mb-10 overflow-x-auto">
            <table className="w-full rounded-xl border border-border bg-surface text-[0.9rem] text-foreground">
              <thead>
                <tr>
                  {["", "Development", "Production"].map((h) => (
                    <th
                      key={h}
                      className="border-b border-border px-4 py-3 text-left font-semibold"
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
                    <td className="border-b border-border px-4 py-3 font-mono text-[0.8rem] text-accent">
                      {label}
                    </td>
                    <td className="border-b border-border px-4 py-3">{dev}</td>
                    <td className="border-b border-border px-4 py-3">{prod}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <Kicker variant="numbered" spacing="sm">
            03 — Reliability
          </Kicker>
          <h2 className="mb-3 text-lg font-semibold text-foreground">Retry Logic</h2>
          <p className="mb-4 text-[1rem] leading-[1.8] text-foreground">
            Database writes in the ingestion pipeline — particularly{" "}
            <code className="rounded border border-border bg-surface px-1 py-0.5 font-mono text-[0.85em]">
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
          <pre className="mb-10 overflow-x-auto rounded-xl border border-border bg-surface p-5 font-mono text-[0.82rem] leading-[1.7] text-foreground">{`for attempt in range(MAX_RETRIES):
    try:
        insert_chunk(chunk)
        break
    except TransientDBError:
        wait(backoff(attempt))
        continue`}</pre>
        </section>

        <section>
          <Kicker variant="numbered" spacing="sm">
            04 — Ingestion
          </Kicker>
          <h2 className="mb-3 text-lg font-semibold text-foreground">Ingestion Queue</h2>
          <div className="mb-10 border border-border border-l-[3px] border-l-accent bg-surface p-4">
            <p className="text-[1rem] leading-[1.8] text-foreground">
              Documents are parsed, chunked, and embedded asynchronously via an{" "}
              <code className="rounded border border-border bg-surface px-1 py-0.5 font-mono text-[0.85em]">
                asyncio.Queue
              </code>{" "}
              with a background worker pool, token bucket rate limiter, exponential backoff with
              jitter, and a dead-letter queue for failed jobs. A Redis replacement is planned for
              Phase 2 to support higher-throughput batch processing at scale.
            </p>
          </div>
        </section>

        <section>
          <Kicker variant="numbered" spacing="sm">
            05 — Vector Search
          </Kicker>
          <h2 className="mb-3 text-lg font-semibold text-foreground">Vector Search Design</h2>
          <p className="mb-4 text-[1rem] leading-[1.8] text-foreground">
            Similarity search is handled by <strong>pgvector</strong> running inside Postgres — no
            separate vector database required. Embeddings are stored alongside document metadata in
            the same schema, keeping the operational footprint minimal.
          </p>
          <pre className="mb-10 overflow-x-auto rounded-xl border border-border bg-surface p-5 font-mono text-[0.82rem] leading-[1.7] text-foreground">{`-- Schema overview (simplified)
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
        </section>

        <section>
          <Kicker variant="numbered" spacing="sm">
            06 — Philosophy
          </Kicker>
          <h2 className="mb-3 text-lg font-semibold text-foreground">Design Principles</h2>
          <div className="mb-10 space-y-3">
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
                className="rounded-xl border border-border bg-surface px-5 py-4"
              >
                <p className="mb-1 text-[0.95rem] font-semibold text-foreground">{title}</p>
                <p className="text-[0.92rem] leading-[1.7] text-foreground">{body}</p>
              </div>
            ))}
          </div>
        </section>
      </div>

      <p className="border-t border-border pt-6 text-[1rem] leading-[1.8] text-foreground">
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
    </DocLayout>
  );
}

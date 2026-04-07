export default function ArchitecturePage() {
  return (
    <main
      style={{
        maxWidth: "720px",
        margin: "0 auto",
        padding: "3rem 1.5rem 6rem",
      }}
    >
      {/* Hero */}
      <section style={{ marginBottom: "3.5rem" }}>
        <p
          style={{
            fontFamily: "monospace",
            fontSize: "0.78rem",
            textTransform: "uppercase",
            letterSpacing: "2px",
            color: "var(--color-accent)",
            marginBottom: "0.75rem",
          }}
        >
          Internals
        </p>
        <h1
          style={{
            fontSize: "2rem",
            fontWeight: 700,
            lineHeight: 1.2,
            color: "var(--color-text)",
            marginBottom: "1rem",
          }}
        >
          Architecture
        </h1>
        <p
          style={{
            fontSize: "1rem",
            lineHeight: 1.8,
            color: "var(--color-muted)",
          }}
        >
          ChatVector is built as a production-ready RAG (Retrieval-Augmented
          Generation) engine — not a general-purpose framework. This page
          summarises how the system is structured internally so contributors and
          evaluators can orient quickly.
        </p>
      </section>

      {/* System Design */}
      <section style={{ marginBottom: "3rem" }}>
        <p
          style={{
            fontFamily: "monospace",
            fontSize: "0.78rem",
            textTransform: "uppercase",
            letterSpacing: "2px",
            color: "var(--color-accent)",
            marginBottom: "0.5rem",
          }}
        >
          01 — System Design
        </p>
        <h2
          style={{
            fontSize: "1.25rem",
            fontWeight: 600,
            color: "var(--color-text)",
            marginBottom: "0.75rem",
          }}
        >
          Layered Architecture Overview
        </h2>
        <p
          style={{
            fontSize: "1rem",
            lineHeight: 1.8,
            color: "var(--color-muted)",
            marginBottom: "1rem",
          }}
        >
          The stack is deliberately layered so each concern is isolated. From
          top to bottom:
        </p>
        <div
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            padding: "1.25rem 1.5rem",
            fontFamily: "monospace",
            fontSize: "0.82rem",
            lineHeight: 1.7,
            color: "var(--color-muted)",
            overflowX: "auto",
          }}
        >
          <pre style={{ margin: 0 }}>{`┌─────────────────────────────────┐
│        API Layer (FastAPI)      │  ← HTTP endpoints, validation
├─────────────────────────────────┤
│     Ingestion / Query Logic     │  ← chunking, embedding, retrieval
├─────────────────────────────────┤
│   Database Strategy (Adapter)   │  ← SQLAlchemy  /  Supabase
├─────────────────────────────────┤
│     Vector Store (pgvector)     │  ← similarity search in Postgres
└─────────────────────────────────┘`}</pre>
        </div>
      </section>

      {/* Database Strategy */}
      <section style={{ marginBottom: "3rem" }}>
        <p
          style={{
            fontFamily: "monospace",
            fontSize: "0.78rem",
            textTransform: "uppercase",
            letterSpacing: "2px",
            color: "var(--color-accent)",
            marginBottom: "0.5rem",
          }}
        >
          02 — Database
        </p>
        <h2
          style={{
            fontSize: "1.25rem",
            fontWeight: 600,
            color: "var(--color-text)",
            marginBottom: "0.75rem",
          }}
        >
          Database Strategy Pattern
        </h2>
        <p
          style={{
            fontSize: "1rem",
            lineHeight: 1.8,
            color: "var(--color-muted)",
            marginBottom: "1.25rem",
          }}
        >
          ChatVector uses a <em>Strategy Pattern</em> for database access. The
          application code never talks to a specific database driver directly —
          it calls a common interface that is backed by either{" "}
          <strong>SQLAlchemy</strong> (local / Docker) or{" "}
          <strong>Supabase</strong> (hosted production). Swapping backends
          requires only an environment variable change.
        </p>

        {/* Dev vs Prod table */}
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "0.75rem",
              fontSize: "0.9rem",
              color: "var(--color-muted)",
            }}
          >
            <thead>
              <tr>
                {["", "Development", "Production"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "0.75rem 1rem",
                      textAlign: "left",
                      borderBottom: "1px solid var(--color-border)",
                      color: "var(--color-text)",
                      fontWeight: 600,
                    }}
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
                <tr key={label as string}>
                  <td
                    style={{
                      padding: "0.65rem 1rem",
                      borderBottom: "1px solid var(--color-border)",
                      fontFamily: "monospace",
                      fontSize: "0.8rem",
                      color: "var(--color-accent)",
                    }}
                  >
                    {label}
                  </td>
                  <td
                    style={{
                      padding: "0.65rem 1rem",
                      borderBottom: "1px solid var(--color-border)",
                    }}
                  >
                    {dev}
                  </td>
                  <td
                    style={{
                      padding: "0.65rem 1rem",
                      borderBottom: "1px solid var(--color-border)",
                    }}
                  >
                    {prod}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Retry Logic */}
      <section style={{ marginBottom: "3rem" }}>
        <p
          style={{
            fontFamily: "monospace",
            fontSize: "0.78rem",
            textTransform: "uppercase",
            letterSpacing: "2px",
            color: "var(--color-accent)",
            marginBottom: "0.5rem",
          }}
        >
          03 — Reliability
        </p>
        <h2
          style={{
            fontSize: "1.25rem",
            fontWeight: 600,
            color: "var(--color-text)",
            marginBottom: "0.75rem",
          }}
        >
          Retry Logic
        </h2>
        <p
          style={{
            fontSize: "1rem",
            lineHeight: 1.8,
            color: "var(--color-muted)",
            marginBottom: "1rem",
          }}
        >
          Database writes in the ingestion pipeline — particularly{" "}
          <code
            style={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "4px",
              padding: "0 4px",
              fontFamily: "monospace",
              fontSize: "0.85em",
            }}
          >
            insert_chunk
          </code>{" "}
          — use explicit retry logic with exponential back-off to handle
          transient failures. This is a blocking dependency for batch ingestion
          and validation features (see{" "}
          <a
            href="https://github.com/chatvector-ai/chatvector-ai/issues/44"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "var(--color-accent)" }}
          >
            #44
          </a>
          ).
        </p>
        <div
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            padding: "1rem 1.25rem",
            fontFamily: "monospace",
            fontSize: "0.82rem",
            lineHeight: 1.7,
            color: "var(--color-muted)",
            overflowX: "auto",
          }}
        >
          <pre style={{ margin: 0 }}>{`for attempt in range(MAX_RETRIES):
    try:
        insert_chunk(chunk)
        break
    except TransientDBError:
        wait(backoff(attempt))
        continue`}</pre>
        </div>
      </section>

      {/* Ingestion Queue */}
      <section style={{ marginBottom: "3rem" }}>
        <p
          style={{
            fontFamily: "monospace",
            fontSize: "0.78rem",
            textTransform: "uppercase",
            letterSpacing: "2px",
            color: "var(--color-accent)",
            marginBottom: "0.5rem",
          }}
        >
          04 — Ingestion
        </p>
        <h2
          style={{
            fontSize: "1.25rem",
            fontWeight: 600,
            color: "var(--color-text)",
            marginBottom: "0.75rem",
          }}
        >
          Ingestion Queue
        </h2>
        <p
          style={{
            fontSize: "1rem",
            lineHeight: 1.8,
            color: "var(--color-muted)",
          }}
        >
          Documents are parsed, chunked, and embedded synchronously in Phase 1.
          The current queue implementation is a simple in-process list. A Redis
          replacement is planned for Phase 2 to support asynchronous and batch
          processing at scale. Chunking quality improvements are also on the
          roadmap before Phase 2 begins.
        </p>
      </section>

      {/* Vector Search */}
      <section style={{ marginBottom: "3rem" }}>
        <p
          style={{
            fontFamily: "monospace",
            fontSize: "0.78rem",
            textTransform: "uppercase",
            letterSpacing: "2px",
            color: "var(--color-accent)",
            marginBottom: "0.5rem",
          }}
        >
          05 — Vector Search
        </p>
        <h2
          style={{
            fontSize: "1.25rem",
            fontWeight: 600,
            color: "var(--color-text)",
            marginBottom: "0.75rem",
          }}
        >
          Vector Search Design
        </h2>
        <p
          style={{
            fontSize: "1rem",
            lineHeight: 1.8,
            color: "var(--color-muted)",
            marginBottom: "1rem",
          }}
        >
          Similarity search is handled by{" "}
          <strong>pgvector</strong> running inside Postgres — no separate vector
          database required. Embeddings are stored alongside document metadata
          in the same schema, keeping the operational footprint minimal.
        </p>
        <div
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            padding: "1rem 1.25rem",
            fontFamily: "monospace",
            fontSize: "0.82rem",
            lineHeight: 1.7,
            color: "var(--color-muted)",
            overflowX: "auto",
          }}
        >
          <pre style={{ margin: 0 }}>{`-- Schema overview (simplified)
chunks (
  id          UUID PRIMARY KEY,
  document_id UUID REFERENCES documents(id),
  content     TEXT,
  embedding   VECTOR(768),   -- pgvector column
  created_at  TIMESTAMPTZ
)

-- Nearest-neighbour query
SELECT content
FROM   chunks
ORDER  BY embedding <-> $query_vector
LIMIT  $top_k;`}</pre>
        </div>
      </section>

      {/* Design Principles */}
      <section style={{ marginBottom: "3.5rem" }}>
        <p
          style={{
            fontFamily: "monospace",
            fontSize: "0.78rem",
            textTransform: "uppercase",
            letterSpacing: "2px",
            color: "var(--color-accent)",
            marginBottom: "0.5rem",
          }}
        >
          06 — Philosophy
        </p>
        <h2
          style={{
            fontSize: "1.25rem",
            fontWeight: 600,
            color: "var(--color-text)",
            marginBottom: "0.75rem",
          }}
        >
          Design Principles
        </h2>
        <div
          style={{
            display: "grid",
            gap: "0.75rem",
          }}
        >
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
              style={{
                background: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                borderRadius: "0.75rem",
                padding: "1rem 1.25rem",
              }}
            >
              <p
                style={{
                  fontWeight: 600,
                  color: "var(--color-text)",
                  marginBottom: "0.25rem",
                  fontSize: "0.95rem",
                }}
              >
                {title}
              </p>
              <p
                style={{
                  fontSize: "0.92rem",
                  lineHeight: 1.7,
                  color: "var(--color-muted)",
                  margin: 0,
                }}
              >
                {body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer link */}
      <p
        style={{
          fontSize: "0.9rem",
          lineHeight: 1.7,
          color: "var(--color-muted)",
          borderTop: "1px solid var(--color-border)",
          paddingTop: "1.5rem",
        }}
      >
        For full architecture details, see{" "}
        <a
          href="https://github.com/chatvector-ai/chatvector-ai/blob/main/ARCHITECTURE.md"
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: "var(--color-accent)" }}
        >
          ARCHITECTURE.md on GitHub
        </a>
        .
      </p>
    </main>
  );
}
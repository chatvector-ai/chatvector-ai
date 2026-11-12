import { DocLayout } from "@/app/components/DocLayout";
import { DocPageHeader } from "@/app/components/DocPageHeader";
import { Kicker } from "@/app/components/Kicker";

import CodeBlock from "../components/CodeBlock";

const bodyClass = "text-foreground/90 text-[1rem] leading-[1.8]";
const cardClass =
  "rounded-xl border border-border bg-surface p-6 transition-colors hover:border-accent/40";

const README_PROVIDER_URL =
  "https://github.com/chatvector-ai/chatvector-ai/blob/main/README.md#provider-configuration";

export default function GettingStartedPage() {
  return (
    <DocLayout>
      <div className="flex flex-col gap-16">
        <div className="space-y-6">
          <DocPageHeader
            kicker="getting started"
            title="Run ChatVector locally."
            description="ChatVector is a backend-first RAG engine for document intelligence. This page summarizes the fastest path to run the API and the demo UI on your machine — aligned with the repository README."
          />
          <div className={cardClass}>
            <p className="text-[1rem] font-medium text-foreground">
              What you will get
            </p>
            <ul className="mt-4 space-y-3 text-[0.98rem] leading-[1.7] text-foreground/90">
              <li>FastAPI backend with RAG ingestion and retrieval.</li>
              <li>PostgreSQL + pgvector via SQLAlchemy (`DATABASE_URL`).</li>
              <li>Next.js demo UI for uploads, chat, batch queries, and citations.</li>
              <li>Development mode bypasses API-key auth — production requires Bearer tokens.</li>
            </ul>
          </div>
        </div>

        <section className="space-y-6">
          <Kicker spacing="lg">prerequisites</Kicker>
          <div className={cardClass}>
            <ul className="space-y-3 text-[0.98rem] leading-[1.7] text-foreground/90">
              <li>
                <a
                  className="text-accent-text underline decoration-transparent hover:decoration-accent"
                  href="https://docs.docker.com/get-docker/"
                  target="_blank"
                  rel="noreferrer"
                >
                  Docker
                </a>{" "}
                with Docker Compose (`docker compose`).
              </li>
              <li>
                <a
                  className="text-accent-text underline decoration-transparent hover:decoration-accent"
                  href="https://nodejs.org/"
                  target="_blank"
                  rel="noreferrer"
                >
                  Node.js
                </a>{" "}
                and npm (for the demo UI).
              </li>
              <li>
                GNU Make (for `make quickstart` and other Makefile shortcuts).
              </li>
              <li>
                Either a hosted LLM provider API key (Gemini or OpenAI), or a
                local{" "}
                <a
                  className="text-accent-text underline decoration-transparent hover:decoration-accent"
                  href="https://ollama.com/"
                  target="_blank"
                  rel="noreferrer"
                >
                  Ollama
                </a>{" "}
                installation. Gemini is the recommended default — see{" "}
                <a
                  className="text-accent-text underline decoration-transparent hover:decoration-accent"
                  href={README_PROVIDER_URL}
                  target="_blank"
                  rel="noreferrer"
                >
                  Provider configuration
                </a>{" "}
                in the README for details instead of duplicating them here.
              </li>
            </ul>
          </div>
        </section>

        <section className="space-y-6">
          <Kicker spacing="lg">quick start</Kicker>
          <p className={bodyClass}>
            From the repository root, start the full development environment with
            one command:
          </p>
          <div className={cardClass}>
            <CodeBlock code="make quickstart" language="bash" />
            <p className="mt-4 text-[0.98rem] leading-[1.7] text-foreground/80">
              The command creates environment files, pauses while you add provider
              credentials when needed, installs frontend dependencies, builds the
              backend Docker image, starts backend services and the
              non-containerized frontend demo, waits for both to become ready,
              and opens browser tabs when supported. Setup is safe to rerun —
              existing `backend/.env` and `frontend-demo/.env.local` files are
              never overwritten.
            </p>
            <p className="mt-3 text-[0.98rem] leading-[1.7] text-foreground/80">
              If provider configuration is already complete,{" "}
              <span className="font-mono text-foreground">make quickstart</span>{" "}
              continues immediately. Returning contributors often use{" "}
              <span className="font-mono text-foreground">make</span> or{" "}
              <span className="font-mono text-foreground">make dev</span> instead
              — run <span className="font-mono text-foreground">make help</span>{" "}
              for the full list.
            </p>
          </div>
        </section>

        <section className="space-y-6">
          <Kicker spacing="lg">defaults and supported formats</Kicker>
          <div className={cardClass}>
            <p className={bodyClass}>
              Upload a supported file, wait until ingestion is{" "}
              <span className="font-mono text-foreground">completed</span>, and ask
              a question. Out of the box:
            </p>
            <ul className="mt-4 space-y-3 text-[0.98rem] leading-[1.7] text-foreground/90">
              <li>
                Retrieval is session-scoped and vector-only. Hybrid search,
                reranking, and query rewrite / expand / step-back stay off until
                you enable them.
              </li>
              <li>
                Follow-up questions in a session can use recent history;
                clearly standalone questions do not spend an extra LLM call to
                rewrite them.
              </li>
              <li>
                Supported uploads are PDF, plain text (`.txt`), Markdown (`.md`),
                HTML (`.html` / `.htm`), and DOCX (`.docx`). Image-only PDFs are
                not OCR&apos;d.
              </li>
            </ul>
          </div>
        </section>

        <section className="space-y-6">
          <Kicker spacing="lg">manual setup</Kicker>
          <p className={bodyClass}>
            Prefer not to use Make? Mirror the README{" "}
            <span className="text-foreground">Manual setup</span> flow:
          </p>
          <div className={cardClass}>
            <ol className="space-y-6 text-[0.98rem] leading-[1.7] text-foreground/90">
              <li>
                <span className="font-medium text-foreground">
                  Copy and configure the backend environment file.
                </span>
                <div className="mt-3">
                  <CodeBlock code="cp backend/.env.example backend/.env" language="bash" />
                </div>
                <p className="mt-3 text-[0.98rem] leading-[1.7] text-foreground/80">
                  Choose providers and credentials in{" "}
                  <span className="text-foreground">backend/.env</span>. See{" "}
                  <a
                    className="text-accent-text underline decoration-transparent hover:decoration-accent"
                    href={README_PROVIDER_URL}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Provider configuration
                  </a>{" "}
                  in the README.
                </p>
              </li>
              <li>
                <span className="font-medium text-foreground">
                  Launch the backend stack.
                </span>
                <div className="mt-3">
                  <CodeBlock code="docker compose up --build" language="bash" />
                </div>
              </li>
              <li>
                <span className="font-medium text-foreground">
                  Start the frontend demo.
                </span>
                <div className="mt-3 space-y-2">
                  <CodeBlock code="cd frontend-demo" language="bash" />
                  <CodeBlock code="npm ci" language="bash" />
                  <CodeBlock
                    code={`echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local`}
                    language="bash"
                  />
                  <CodeBlock code="npm run dev" language="bash" />
                </div>
                <p className="mt-3 text-[0.98rem] leading-[1.7] text-foreground/80">
                  Frontend runs at{" "}
                  <span className="text-foreground">http://localhost:3000</span>
                  .
                </p>
              </li>
            </ol>
          </div>
        </section>

        <section className="space-y-6">
          <Kicker spacing="lg">test the api</Kicker>
          <p className={bodyClass}>
            Once the stack is up, open Swagger UI and try the core endpoints to
            upload a document, check status, and ask questions.
          </p>
          <div className={cardClass}>
            <div className="space-y-3 text-[0.98rem] leading-[1.7] text-foreground/90">
              <p>
                API root:{" "}
                <span className="text-foreground">http://localhost:8000</span>
              </p>
              <p>
                Swagger UI:{" "}
                <span className="text-foreground">http://localhost:8000/docs</span>
              </p>
            </div>
            <div className="mt-6 space-y-4">
              <CodeBlock
                code={`POST /upload    -> upload PDF, TXT, Markdown, HTML, or DOCX; returns document_id
GET  /documents/{document_id}/status
POST /chat      -> ask questions with citations`}
                language="text"
              />
            </div>
          </div>
        </section>

        <section className="space-y-6">
          <Kicker spacing="lg">useful commands</Kicker>
          <div className={cardClass}>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-[0.95rem] text-foreground/90">
                <thead>
                  <tr className="border-b border-border">
                    <th className="py-3 pr-4 font-medium text-foreground">
                      Command
                    </th>
                    <th className="py-3 font-medium text-foreground">Purpose</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      make quickstart
                    </td>
                    <td className="py-3 text-foreground/80">
                      Create env, pause for credentials, then start everything
                    </td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      make
                    </td>
                    <td className="py-3 text-foreground/80">
                      Start backend + frontend, open browser tabs
                    </td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      make dev
                    </td>
                    <td className="py-3 text-foreground/80">
                      Start backend + frontend without opening tabs
                    </td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      make stop
                    </td>
                    <td className="py-3 text-foreground/80">
                      Stop this repo&apos;s frontend process and Docker services
                    </td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      docker compose logs -f api
                    </td>
                    <td className="py-3 text-foreground/80">Tail API logs</td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      docker compose down -v
                    </td>
                    <td className="py-3 text-foreground/80">
                      Stop containers and delete data volumes
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="space-y-6">
          <Kicker spacing="lg">next steps</Kicker>
          <div className={`${cardClass} mt-2`}>
            <p className={bodyClass}>
              For full setup details, provider matrices, and Docker shortcuts,
              see the{" "}
              <a
                href="https://github.com/chatvector-ai/chatvector-ai/blob/main/README.md"
                className="text-accent-text underline decoration-transparent hover:decoration-accent"
                target="_blank"
                rel="noreferrer"
              >
                README on GitHub
              </a>
              .
            </p>
          </div>
        </section>
      </div>
    </DocLayout>
  );
}

import Image from "next/image";

const kickerClass =
  "font-mono text-[0.78rem] uppercase tracking-[2px] text-accent";
const bodyClass = "text-muted text-[1rem] leading-[1.8]";
const cardClass =
  "rounded-xl border border-border bg-surface p-6 transition-colors hover:border-accent/40";
const codeClass =
  "rounded-xl border border-border bg-surface px-5 py-4 font-mono text-[0.82rem] leading-[1.75] text-foreground";

export default function GettingStartedPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <main className="mx-auto flex w-full max-w-[720px] flex-col gap-16 px-6 pb-24 pt-16">
        <div className="flex justify-center">
          <Image
            src="/redirect-logo.svg"
            alt="ChatVector logo"
            width={80}
            height={80}
            priority
          />
        </div>
        <section className="space-y-6">
          <p className={`${kickerClass} block mb-4`}>
            {"// getting started"}
          </p>
          <h1 className="text-3xl font-bold leading-[1.1] tracking-[-1px]">
            Run ChatVector locally in minutes.
          </h1>
          <p className={bodyClass}>
            ChatVector is a backend-first RAG engine for document intelligence.
            This page summarizes the fastest path to run the API and the demo UI
            on your machine.
          </p>
          <div className={cardClass}>
            <p className="text-foreground text-[1rem] font-medium">
              What you will get
            </p>
            <ul className="mt-4 space-y-3 text-muted text-[0.98rem] leading-[1.7]">
              <li>FastAPI backend with RAG ingestion and retrieval.</li>
              <li>PostgreSQL + pgvector for semantic search.</li>
              <li>Next.js demo UI for uploads, chat, and citations.</li>
            </ul>
          </div>
        </section>

        <section className="space-y-6">
          <p className={`${kickerClass} block mb-4`}>{"// prerequisites"}</p>
          <div className={cardClass}>
            <ul className="space-y-3 text-muted text-[0.98rem] leading-[1.7]">
              <li>Docker + Docker Compose installed.</li>
              <li>Google AI Studio API key for embeddings + LLM.</li>
              <li>Node.js 18+ (for the demo UI).</li>
            </ul>
          </div>
        </section>

        <section className="space-y-6">
          <p className={`${kickerClass} block mb-4`}>{"// quick setup"}</p>
          <div className={cardClass}>
            <ol className="space-y-6 text-muted text-[0.98rem] leading-[1.7]">
              <li>
                <span className="text-foreground font-medium">Star the repo.</span>{" "}
                <a
                  className="text-accent underline decoration-transparent hover:decoration-accent"
                  href="https://github.com/chatvector-ai/chatvector-ai"
                  target="_blank"
                  rel="noreferrer"
                >
                  ChatVector on GitHub
                </a>{" "}
                ⭐
              </li>
              <li>
                <span className="text-foreground font-medium">
                  Create the backend environment file.
                </span>
                <div className="mt-3">
                  <pre className={codeClass}>cp backend/.env.example backend/.env</pre>
                </div>
                <p className="mt-3 text-muted text-[0.98rem] leading-[1.7]">
                  Edit the file and set <span className="text-foreground">GEN_AI_KEY</span>.
                </p>
              </li>
              <li>
                <span className="text-foreground font-medium">
                  Create the frontend environment file.
                </span>
                <div className="mt-3">
                  <pre className={codeClass}>
                    {`NEXT_PUBLIC_API_URL=http://localhost:8000`}
                  </pre>
                </div>
                <p className="mt-3 text-muted text-[0.98rem] leading-[1.7]">
                  Save this as <span className="text-foreground">frontend-demo/.env.local</span>.
                </p>
              </li>
              <li>
                <span className="text-foreground font-medium">
                  Launch the backend stack.
                </span>
                <div className="mt-3">
                  <pre className={codeClass}>docker compose up --build</pre>
                </div>
              </li>
              <li>
                <span className="text-foreground font-medium">
                  Start the frontend demo.
                </span>
                <div className="mt-3 space-y-2">
                  <pre className={codeClass}>cd frontend-demo</pre>
                  <pre className={codeClass}>npm install</pre>
                  <pre className={codeClass}>npm run dev</pre>
                </div>
                <p className="mt-3 text-muted text-[0.98rem] leading-[1.7]">
                  Frontend runs at <span className="text-foreground">http://localhost:3000</span>.
                </p>
              </li>
            </ol>
          </div>
        </section>

        <section className="space-y-6">
          <p className={`${kickerClass} block mb-4`}>{"// test the api"}</p>
          <p className={bodyClass}>
            Once the containers are up, hit the root endpoint and open Swagger
            UI. Then try the three core endpoints to upload a document, check
            status, and ask questions.
          </p>
          <div className={cardClass}>
            <div className="space-y-3 text-muted text-[0.98rem] leading-[1.7]">
              <p>
                Root: <span className="text-foreground">http://localhost:8000</span>
              </p>
              <p>
                Swagger UI:{" "}
                <span className="text-foreground">http://localhost:8000/docs</span>
              </p>
            </div>
            <div className="mt-6 space-y-4">
              <pre className={codeClass}>
                {`POST /upload    -> upload a PDF, returns document_id\nGET  /documents/{document_id}/status\nPOST /chat      -> ask questions with citations`}
              </pre>
            </div>
          </div>
        </section>

        <section className="space-y-6">
          <p className={`${kickerClass} block mb-4`}>{"// docker commands"}</p>
          <div className={cardClass}>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-[0.95rem] text-muted">
                <thead>
                  <tr className="border-b border-border">
                    <th className="py-3 pr-4 font-medium text-foreground">Command</th>
                    <th className="py-3 font-medium text-foreground">Purpose</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      docker compose up --build
                    </td>
                    <td className="py-3">Start API + database</td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      docker compose down
                    </td>
                    <td className="py-3">Stop containers</td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      docker compose logs -f api
                    </td>
                    <td className="py-3">Tail API logs</td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      docker compose up db
                    </td>
                    <td className="py-3">Run database only</td>
                  </tr>
                  <tr className="transition-colors hover:bg-accent/5">
                    <td className="py-3 pr-4 font-mono text-foreground">
                      docker compose down -v
                    </td>
                    <td className="py-3">Stop and remove data volumes</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="space-y-6">
          <p className={`${kickerClass} block mb-4`}>{"// next steps"}</p>
          <div className={`${cardClass} mt-2`}>
            <p className={bodyClass}>
              For full setup details, see the{" "}
              <a
                href="https://github.com/chatvector-ai/chatvector-ai/blob/main/README.md"
                className="text-accent underline decoration-transparent hover:decoration-accent"
                target="_blank"
                rel="noreferrer"
              >
                README on GitHub
              </a>
              .
            </p>
          </div>
        </section>
      </main>
    </div>
  );
}

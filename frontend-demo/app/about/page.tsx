import Link from "next/link";
import Footer from "../components/home/Footer";

export default function AboutPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div className="max-w-[720px] mx-auto px-4 py-16 flex-1">
        {/* Section 1: What is ChatVector */}
        <section className="mb-20">
          <span className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent block mb-4">
            What is ChatVector
          </span>
          <h1 className="text-3xl font-bold mb-6 text-foreground">
            A developer-focused RAG engine you can deploy as a service.
          </h1>
          <p className="text-muted text-lg leading-relaxed mb-6">
            Most RAG implementations today are fragile, vendor-locked, or require significant plumbing to productionize. ChatVector solves this by providing a clean, extensible backend foundation for document intelligence. It handles the full document Q&A lifecycle—from ingestion and semantic chunking to vector storage and cited response generation—all through a clean HTTP API.
          </p>
        </section>

        {/* Section 2: Who is this for */}
        <section className="mb-20">
          <h2 className="text-2xl font-semibold mb-6 text-foreground">
            Who is this for
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              {
                title: "Developers",
                description:
                  "Building document intelligence tools or internal knowledge systems",
              },
              {
                title: "Backend Engineers",
                description:
                  "Who want a solid RAG foundation without heavy abstractions",
              },
              {
                title: "AI/ML Practitioners",
                description:
                  "Experimenting with chunking, retrieval, and prompt strategies",
              },
              {
                title: "Open-Source Contributors",
                description:
                  "Interested in retrieval systems, embeddings, and LLM orchestration",
              },
            ].map((persona) => (
              <div
                key={persona.title}
                className="bg-surface border border-border rounded-xl px-5 py-4 transition-all hover:border-accent/40"
              >
                <h3 className="font-bold text-foreground mb-1">
                  {persona.title}
                </h3>
                <p className="text-muted text-base leading-relaxed">
                  {persona.description}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Section 3: ChatVector vs frameworks */}
        <section className="mb-20">
          <span className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent block mb-4">
            ChatVector vs frameworks
          </span>
          <div className="mt-6 overflow-x-auto rounded-xl border border-border bg-surface">
            <table className="w-full border-collapse text-left text-base leading-relaxed">
              <thead>
                <tr className="border-b border-border bg-background/30 text-foreground">
                  <th className="px-5 py-4 font-bold">Aspect</th>
                  <th className="px-5 py-4 font-bold text-accent">ChatVector</th>
                  <th className="px-5 py-4 font-bold">General Framework</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {[
                  {
                    aspect: "Primary Goal",
                    cv: "Deployable backend service",
                    gf: "Modular components",
                  },
                  {
                    aspect: "Out-of-the-box",
                    cv: "Fully functional FastAPI service",
                    gf: "Tools you wire together",
                  },
                  {
                    aspect: "Architecture",
                    cv: "Batteries-included, opinionated",
                    gf: "Modular building blocks",
                  },
                  {
                    aspect: "Best for",
                    cv: "Teams who need a document Q&A API now",
                    gf: "Novel AI agents and research",
                  },
                  {
                    aspect: "Path to production",
                    cv: "Short — configure, deploy, integrate",
                    gf: "Long — significant additional work",
                  },
                ].map((row, i) => (
                  <tr
                    key={i}
                    className="group transition-colors hover:bg-accent/5"
                  >
                    <td className="px-5 py-4 font-medium text-foreground">
                      {row.aspect}
                    </td>
                    <td className="px-5 py-4 text-muted group-hover:text-foreground">
                      {row.cv}
                    </td>
                    <td className="px-5 py-4 text-muted group-hover:text-foreground">
                      {row.gf}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Section 4: Footer CTA */}
        <div className="pt-12 border-t border-border text-center">
          <p className="text-muted mb-8 text-lg leading-relaxed">
            Ready to get started? Set up ChatVector in under 5 minutes.
          </p>
          <Link
            href="/getting-started"
            className="inline-flex items-center justify-center rounded-md border border-accent bg-accent/10 px-8 py-3 text-base font-bold text-accent no-underline transition-all hover:bg-accent/20 hover:scale-[1.02]"
          >
            Getting Started
          </Link>
        </div>
      </div>
      <Footer />
    </div>
  );
}

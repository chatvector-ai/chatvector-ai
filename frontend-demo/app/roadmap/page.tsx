import Link from "next/link";
import { DocLayout } from "@/app/components/DocLayout";
import { DocPageHeader } from "@/app/components/DocPageHeader";

const phases = [
  {
    number: "Phase 1",
    title: "Stabilize & Optimize Core Engine",
    status: "Complete",
    statusStyles: "bg-accent text-black",
    description:
      "Core RAG backend hardened for reliability, observability, and performance. Shipped features include a robust ingestion pipeline, centralized retry logic, and built-in observability.",
  },
  {
    number: "Phase 2",
    title: "Enhance Developer Experience",
    status: "Current",
    statusStyles: "bg-blue text-white",
    description:
      "Active work areas focusing on a Redis-backed durable ingestion queue, improved observability, advanced chunking strategies, and wiring up the document upload UI.",
  },
  {
    number: "Phase 3",
    title: "Scale & Specialize",
    status: "Later",
    statusStyles: "border border-border bg-surface text-foreground/80",
    description:
      "Long-term vision for a production-ready document intelligence platform. Future goals include authentication, multi-tenancy, specialized pipelines, and ecosystem growth.",
  },
];

export default function RoadmapPage() {
  return (
    <DocLayout>
      <DocPageHeader
        kicker="future outlook"
        title="Roadmap"
        description="Phased delivery from stabilizing the core engine through developer experience and long-term scale."
      />

      <div className="mt-12 grid gap-6">
        {phases.map((phase, i) => (
          <section
            key={i}
            className="rounded-r-xl border border-border border-l-[3px] border-l-accent bg-surface p-8 shadow-sm"
          >
            <div className="mb-4 flex items-center justify-between">
              <span className="text-[0.7rem] uppercase tracking-widest text-accent/80 font-mono">
                {phase.number}
              </span>
              <span
                className={`rounded-full px-3 py-1 text-[0.65rem] font-bold uppercase tracking-wider ${phase.statusStyles}`}
              >
                {phase.status}
              </span>
            </div>

            <h2 className="mb-3 text-xl font-semibold text-foreground">{phase.title}</h2>

            <p className="text-[1rem] leading-[1.8] text-foreground/90">{phase.description}</p>
          </section>
        ))}
      </div>

      <div className="mt-16 flex flex-col gap-6 border-t border-border pt-8">
        <div>
          <p className="mb-2 text-sm text-foreground/80">Want to see what we&apos;re building right now?</p>
          <Link
            href="https://github.com/orgs/chatvector-ai/projects/1"
            className="inline-flex items-center gap-2 font-medium text-accent transition-colors hover:text-accent/80"
          >
            Check the ChatVector-AI Development Board →
          </Link>
        </div>

        <p className="border-l border-border pl-4 text-sm italic text-foreground/80">
          For full roadmap details, see{" "}
          <Link
            href="https://github.com/chatvector-ai/chatvector-ai/blob/main/ROADMAP.md"
            className="underline transition-colors hover:text-foreground"
          >
            ROADMAP.md on GitHub
          </Link>
          .
        </p>
      </div>
    </DocLayout>
  );
}

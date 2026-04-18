import React from 'react';
import Link from 'next/link';

// Data for the Roadmap phases
const phases = [
  {
    number: "Phase 1",
    title: "Stabilize & Optimize Core Engine",
    status: "Complete",
    statusStyles: "bg-accent text-black",
    description: "Core RAG backend hardened for reliability, observability, and performance. Shipped features include a robust ingestion pipeline, centralized retry logic, and built-in observability."
  },
  {
    number: "Phase 2",
    title: "Enhance Developer Experience",
    status: "Current",
    statusStyles: "bg-blue text-white",
    description: "Active work areas focusing on a Redis-backed durable ingestion queue, improved observability, advanced chunking strategies, and wiring up the document upload UI."
  },
  {
    number: "Phase 3",
    title: "Scale & Specialize",
    status: "Later",
    statusStyles: "bg-surface text-muted border border-border",
    description: "Long-term vision for a production-ready document intelligence platform. Future goals include authentication, multi-tenancy, specialized pipelines, and ecosystem growth."
  }
];

export default function RoadmapPage() {
  return (
    <div className="min-h-screen bg-background text-foreground py-20 px-4">
      <div className="max-w-[720px] mx-auto">
        
        {/* Section Kicker - Mono styled as per requirements */}
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-4">
          Future Outlook
        </p>

        <h1 className="text-4xl font-bold mb-12 tracking-tight">Project Roadmap</h1>

        <h2 className="sr-only">Development phases</h2>
        <div className="grid gap-6">
          {phases.map((phase, i) => (
            <section 
              key={i} 
              className="bg-surface border border-border border-l-[3px] border-l-accent p-8 rounded-r-xl shadow-sm"
            >
              <div className="flex items-center justify-between mb-4">
                <span className="font-mono text-[0.7rem] uppercase tracking-widest text-accent/80">
                  {phase.number}
                </span>
                <span className={`px-3 py-1 rounded-full text-[0.65rem] font-bold uppercase tracking-wider ${phase.statusStyles}`}>
                  {phase.status}
                </span>
              </div>
              
              <h3 className="text-xl font-semibold mb-3 text-foreground">
                {phase.title}
              </h3>
              
              <p className="text-muted text-[1rem] leading-[1.8]">
                {phase.description}
              </p>
            </section>
          ))}
        </div>

        {/* Footer & Links Section */}
        <div className="mt-16 pt-8 border-t border-border flex flex-col gap-6">
          <div>
            <p className="text-muted text-sm mb-2">Want to see what we&apos;re building right now?</p>
            <Link 
              href="https://github.com/orgs/chatvector-ai/projects/1" 
              className="text-accent hover:text-accent/80 transition-colors font-medium inline-flex items-center gap-2"
            >
              Check the ChatVector-AI Development Board →
            </Link>
          </div>
          
          <p className="text-muted text-sm italic border-l border-border pl-4">
            For full roadmap details, see{" "}
            <Link 
              href="https://github.com/chatvector-ai/chatvector-ai/blob/main/ROADMAP.md" 
              className="underline hover:text-foreground transition-colors"
            >
              ROADMAP.md on GitHub
            </Link>.
          </p>
        </div>
      </div>
    </div>
  );
}
"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import ErrorState from "../components/ErrorState";
import { DocLayout } from "@/app/components/DocLayout";
import { DocPageHeader } from "@/app/components/DocPageHeader";

type Contributor = {
  login: string;
  avatar_url: string;
  html_url: string;
  contributions: number;
};

export default function ContributorsPage() {
  const [contributors, setContributors] = useState<Contributor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchContributors = useCallback(() => {
    setLoading(true);
    setError("");
    fetch(
      "https://api.github.com/repos/chatvector-ai/chatvector-ai/contributors",
    )
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch");
        return res.json();
      })
      .then((data) => {
        const sorted = data.sort(
          (a: Contributor, b: Contributor) => b.contributions - a.contributions,
        );
        setContributors(sorted);
        setLoading(false);
      })
      .catch(() => {
        setError("Failed to load contributors");
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchContributors();
  }, [fetchContributors]);

  return (
    <DocLayout>
      <DocPageHeader
        kicker="thanks"
        title="Contributors"
        description="A special thanks to everyone who has contributed code, documentation, ideas, or feedback. This project is shaped by the community."
      />

      {loading && (
        <div className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-3">
          {Array.from({ length: 9 }).map((_, i) => (
            <div
              key={i}
              className="flex animate-pulse flex-col items-center gap-3 rounded-lg border border-border bg-surface p-4"
            >
              <div className="h-16 w-16 rounded-full bg-border" />
              <div className="h-3 w-36 rounded bg-border md:w-48" />
              <div className="h-3 w-24 rounded bg-border md:w-28" />
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="mt-10">
          <ErrorState
            heading="Failed to load contributors"
            message="Something went wrong fetching from GitHub."
            onRetry={fetchContributors}
          />
        </div>
      )}

      {!loading && !error && (
        <div className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-3">
          {contributors.map((c) => (
            <a
              key={c.login}
              href={c.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex flex-col items-center rounded-lg border border-border bg-surface p-4 transition hover:scale-[1.02] hover:border-accent"
            >
              <Image
                src={c.avatar_url}
                alt={c.login}
                width={64}
                height={64}
                className="mb-3 rounded-full"
              />

              <p className="font-mono text-accent">@{c.login}</p>

              <p className="text-sm text-foreground/80">
                {c.contributions} contributions
              </p>
            </a>
          ))}
        </div>
      )}
    </DocLayout>
  );
}

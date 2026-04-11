"use client";

import { useEffect, useState, useCallback } from "react";
import Image from "next/image";
import ErrorState from "../components/ErrorState";

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
        // sort explicitly (even though API already does)
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
    <div className="max-w-[720px] mx-auto px-4 py-10">
      <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-2">
        {"// thanks"}
      </p>
      <h1 className="text-3xl font-bold mb-4 text-foreground">Contributors</h1>
      <p className="text-foreground text-[1rem] leading-[1.8] mb-8">
        A special thanks to everyone who has contributed code, documentation,
        ideas, or feedback. This project is shaped by the community.
      </p>

      {loading && (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {Array.from({ length: 9 }).map((_, i) => (
            <div
              key={i}
              className="animate-pulse bg-surface border border-border rounded-lg p-4 flex flex-col items-center gap-3"
            >
              <div className="w-16 h-16 rounded-full bg-border" />
              <div className="h-3 w-36 md:w-48 rounded bg-border" />
              <div className="h-3 w-24 md:w-28 rounded bg-border" />
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
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {contributors.map((c) => (
            <a
              key={c.login}
              href={c.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="bg-surface border border-border p-4 rounded-lg flex flex-col items-center hover:border-accent hover:scale-[1.02] transition"
            >
              <Image
                src={c.avatar_url}
                alt={c.login}
                width={64}
                height={64}
                className="rounded-full mb-3"
              />

              <p className="font-mono text-accent">@{c.login}</p>

              <p className="text-muted text-sm">
                {c.contributions} contributions
              </p>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

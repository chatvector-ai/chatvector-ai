"use client";

import { useEffect, useState } from "react";

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

  useEffect(() => {
    fetch("https://api.github.com/repos/chatvector-ai/chatvector-ai/contributors")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch");
        return res.json();
      })
      .then((data) => {
        // sort explicitly (even though API already does)
        const sorted = data.sort(
          (a: Contributor, b: Contributor) =>
            b.contributions - a.contributions
        );
        setContributors(sorted);
        setLoading(false);
      })
      .catch(() => {
        setError("Failed to load contributors");
        setLoading(false);
      });
  }, []);

  return (
    <div className="max-w-[720px] mx-auto px-4 py-10">
      <h1 className="text-3xl font-bold mb-6 text-foreground">
        Contributors
      </h1>

      {loading && (
        <p className="text-muted text-center mt-6">
  Loading contributors...
</p>
      )}

      {error && (
       <p className="text-foreground text-center mt-6">
  {error}
</p>
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
              <img
                src={c.avatar_url}
                alt={c.login}
                className="w-16 h-16 rounded-full mb-3"
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
import { DocLayout } from "@/app/components/DocLayout";
import { DocPageHeader } from "@/app/components/DocPageHeader";
import { Kicker } from "@/app/components/Kicker";

export default function ContributingPage() {
  return (
    <DocLayout>
      <DocPageHeader
        kicker="contributing"
        title="Contributing to ChatVector"
        description="Learn how to get started with contributing to ChatVector and find ways to get involved."
      />

      <div className="mt-10 space-y-10">
        <section>
          <Kicker spacing="sm">pick an issue and go</Kicker>
          <div className="mb-6 border border-border border-l-[3px] border-l-accent bg-surface p-4">
            <p className="text-[1rem] leading-[1.8] text-foreground">
              Browse open issues, find something interesting, and start working on it. No
              permission needed and no formal claim process — if you want to tackle an issue,
              go for it and open a PR when you&apos;re done.
            </p>
            <p className="mt-4 text-[1rem] leading-[1.8] text-foreground">
              Want to let other contributors know you&apos;re on it? Leave a quick comment on
              the issue. That&apos;s helpful but totally optional.
            </p>
          </div>
        </section>

        <section>
          <Kicker spacing="sm">finding issues</Kicker>
          <div className="mb-6 border border-border border-l-[3px] border-l-accent bg-surface p-4">
            <p className="text-[1rem] leading-[1.8] text-foreground">
              Look for issues labeled{" "}
              <code className="rounded border border-border bg-surface px-1 py-0.5">
                good first issue
              </code>{" "}
              to get started easily. You can also explore the project board to see what is currently being worked on or find tasks that match your interests.
            </p>
          </div>
        </section>

        <section>
          <Kicker spacing="sm">branch & commit naming</Kicker>
          <div className="mb-6 border border-border border-l-[3px] border-l-accent bg-surface p-4">
            <p className="text-[1rem] leading-[1.8] text-foreground">
              Use a clear naming convention like{" "}
              <code className="rounded border border-border bg-surface px-1 py-0.5">
                type/description
              </code>
              . Examples include{" "}
              <code className="rounded border border-border bg-surface px-1 py-0.5">
                feat/add-feature
              </code>
              ,{" "}
              <code className="rounded border border-border bg-surface px-1 py-0.5">
                fix/bug-fix
              </code>
              , and{" "}
              <code className="rounded border border-border bg-surface px-1 py-0.5">
                docs/update-readme
              </code>
              . Keep your commits focused and descriptive.
            </p>
          </div>
        </section>

        <section>
          <Kicker spacing="sm">pull request process</Kicker>
          <div className="mb-6 border border-border border-l-[3px] border-l-accent bg-surface p-4">
            <p className="text-[1rem] leading-[1.8] text-foreground">
              Create a new branch, implement your changes, and open a pull request from your fork
              to the main repository. Describe what changed and how you tested it. If your work
              relates to an issue, mentioning{" "}
              <code className="rounded border border-border bg-surface px-1 py-0.5">
                Closes #123
              </code>{" "}
              in the PR description helps track it on the project board — also optional.
            </p>
          </div>
        </section>

        <section>
          <Kicker spacing="sm">helpful links</Kicker>
          <ul className="mb-6 space-y-2">
            <li>
              <a
                href="https://www.loom.com/share/c41bdbff541f47d49efcb48920cba382"
                className="text-muted transition-colors hover:text-foreground"
              >
                Loom Contributor Video
              </a>
            </li>
            <li>
              <a
                href="https://github.com/chatvector-ai/chatvector-ai/discussions"
                className="text-muted transition-colors hover:text-foreground"
              >
                GitHub Discussions
              </a>
            </li>
            <li>
              <a
                href="https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22"
                className="text-muted transition-colors hover:text-foreground"
              >
                Good First Issues
              </a>
            </li>
            <li>
              <a
                href="https://github.com/chatvector-ai/chatvector-ai/projects"
                className="text-muted transition-colors hover:text-foreground"
              >
                Project Board
              </a>
            </li>
            <li>
              <a
                href="https://github.com/chatvector-ai/chatvector-ai/blob/main/README.md"
                className="text-muted transition-colors hover:text-foreground"
              >
                Project README
              </a>
            </li>
          </ul>
        </section>
      </div>

      <p className="text-[1rem] leading-[1.8] text-foreground">
        For the full contribution guide, see{" "}
        <a
          href="https://github.com/chatvector-ai/chatvector-ai/blob/main/CONTRIBUTING.md"
          className="text-accent hover:text-accent/80"
        >
          CONTRIBUTING.md on GitHub
        </a>
        .
      </p>
    </DocLayout>
  );
}

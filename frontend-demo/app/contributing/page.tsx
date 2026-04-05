export default function ContributingPage() {
  return (
    <div className="max-w-[720px] mx-auto px-4 py-10">
      
      <h1 className="text-3xl font-bold mb-6 text-foreground">
        Contributing
      </h1>

      <p className="text-foreground text-[1rem] leading-[1.8] mb-6">
        Learn how to get started with contributing to ChatVector and find ways to get involved.
      </p>

      {/* Finding Issues */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        Finding Issues
      </h2>
      <div className="bg-surface border border-border border-l-[3px] border-l-accent p-4 mb-6">
        <p className="text-foreground text-[1rem] leading-[1.8]">
          Look for issues labeled{" "}
          <code className="px-1 py-0.5 bg-surface border border-border rounded">
            good first issue
          </code>{" "}
          to get started easily. You can also explore the project board to see what is currently being worked on or find tasks that match your interests.
        </p>
      </div>

      {/* Branch Naming */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        Branch & Commit Naming
      </h2>
      <div className="bg-surface border border-border border-l-[3px] border-l-accent p-4 mb-6">
        <p className="text-foreground text-[1rem] leading-[1.8]">
          Use a clear naming convention like{" "}
          <code className="px-1 py-0.5 bg-surface border border-border rounded">
            type/description
          </code>
          . Examples include{" "}
          <code className="px-1 py-0.5 bg-surface border border-border rounded">
            feat/add-feature
          </code>
          ,{" "}
          <code className="px-1 py-0.5 bg-surface border border-border rounded">
            fix/bug-fix
          </code>
          , and{" "}
          <code className="px-1 py-0.5 bg-surface border border-border rounded">
            docs/update-readme
          </code>
          . Keep your commits focused and descriptive.
        </p>
      </div>

      {/* PR Process */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        Pull Request Process
      </h2>
      <div className="bg-surface border border-border border-l-[3px] border-l-accent p-4 mb-6">
        <p className="text-foreground text-[1rem] leading-[1.8]">
          Create a new branch, implement your changes, and open a pull request from your fork to the main repository. 
          Make sure to clearly describe what your PR does, how it was tested, and follow the checklist before submitting.
        </p>
      </div>

      {/* Links */}
      <h2 className="mt-8 mb-2 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        Helpful Links
      </h2>
      <ul className="mb-6 space-y-2">
        <li>
          <a 
            href="https://www.loom.com/share/c41bdbff541f47d49efcb48920cba382" 
            className="text-accent hover:text-accent/80"
          >
            Loom Contributor Video
          </a>
        </li>
        <li>
          <a 
            href="https://github.com/chatvector-ai/chatvector-ai/discussions" 
            className="text-accent hover:text-accent/80"
          >
            GitHub Discussions
          </a>
        </li>
        <li>
          <a 
            href="https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22" 
            className="text-accent hover:text-accent/80"
          >
            Good First Issues
          </a>
        </li>
        <li>
          <a 
            href="https://github.com/chatvector-ai/chatvector-ai/projects" 
            className="text-accent hover:text-accent/80"
          >
            Project Board
          </a>
        </li>
        <li>
          <a 
            href="https://github.com/chatvector-ai/chatvector-ai/blob/main/README.md" 
            className="text-accent hover:text-accent/80"
          >
            Project README
          </a>
        </li>
      </ul>

      {/* Footer */}
      <p className="text-foreground text-[1rem] leading-[1.8]">
        For the full contribution guide, see{" "}
        <a 
          href="https://github.com/chatvector-ai/chatvector-ai/blob/main/CONTRIBUTING.md"
          className="text-accent hover:text-accent/80"
        >
          CONTRIBUTING.md on GitHub
        </a>.
      </p>

    </div>
  );
}
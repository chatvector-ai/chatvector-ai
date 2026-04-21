import React from "react";
import { GITHUB_REPO, SYNTAX } from "../lib/constants";
interface CodeBlockProps {
  filename?: string;
  language?: "python" | "bash" | "sql" | "text";
  code?: string;
  children?: React.ReactNode;
  showLineNumbers?: boolean;
  className?: string;
}
const CodeBlock = (
  { filename, children, language, code }: CodeBlockProps,
  //   showLineNumbers?: boolean,
  //   className?: string,
) => {
  if (filename) {
    return (
      <div className="overflow-hidden rounded-xl border border-border bg-code-bg">
        <div className="flex items-center gap-2 border-b border-border bg-[rgb(24,28,34)] px-4 py-3">
          {/* macOS traffic-light dots — intentional non-token colors */}
          <div className="size-2.5 rounded-full bg-[rgb(255,95,87)]" />
          <div className="size-2.5 rounded-full bg-[rgb(254,188,46)]" />
          <div className="size-2.5 rounded-full bg-[rgb(40,200,64)]" />
          <span className="ml-auto font-mono text-xs text-muted">
            {filename}
          </span>
        </div>
        {children}
      </div>
    );
  } else {
    return (
      <pre className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] p-4 overflow-x-auto">
        <code>{code}</code>
      </pre>
    );
  }
};
export default CodeBlock;

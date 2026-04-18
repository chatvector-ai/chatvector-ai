"use client";

import Image from "next/image";

type Props = {
  kicker?: string; // defaults to "// error"
  heading: string;
  message: string;
  onRetry?: () => void; // renders a retry button when provided
  /** Use "h1" only when this is the sole page title (e.g. 404). Default "h2" for inline error blocks. */
  headingLevel?: "h1" | "h2";
};

export default function ErrorState({
  kicker = "// error",
  heading,
  message,
  onRetry,
  headingLevel = "h2",
}: Props) {
  return (
    <div className="flex flex-col items-center text-center gap-3">
      {/* Both images rendered; CSS shows/hides based on data-theme on <html> */}
      <Image
        src="/redirect-logo-dark.svg"
        alt="Error logo"
        width={160}
        height={160}
        priority
        className="[[data-theme=light]_&]:hidden"
      />
      <Image
        src="/redirect-logo-light.svg"
        alt="Error logo"
        width={160}
        height={160}
        priority
        className="hidden [[data-theme=light]_&]:block"
      />
      <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        {kicker}
      </p>
      {headingLevel === "h1" ? (
        <h1 className="text-foreground font-semibold text-xl">{heading}</h1>
      ) : (
        <h2 className="text-foreground font-semibold text-xl">{heading}</h2>
      )}
      <p className="text-muted text-[1rem]">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 border border-border bg-transparent hover:bg-surface text-foreground rounded-lg px-5 py-2 transition-colors"
        >
          Retry
        </button>
      )}
    </div>
  );
}

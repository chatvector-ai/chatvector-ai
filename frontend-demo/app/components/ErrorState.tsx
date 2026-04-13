import Image from "next/image";

type Props = {
  kicker?: string; // defaults to "// error"
  heading: string;
  message: string;
  onRetry?: () => void; // renders a retry button when provided
};

export default function ErrorState({
  kicker = "// error",
  heading,
  message,
  onRetry,
}: Props) {
  return (
    <div className="flex flex-col items-center text-center gap-3">
      <Image
        src="/redirect-logo-dark.svg"
        alt="Error logo"
        width={80}
        height={80}
        priority
      />
      <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
        {kicker}
      </p>
      <h2 className="text-foreground font-semibold text-xl">{heading}</h2>
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

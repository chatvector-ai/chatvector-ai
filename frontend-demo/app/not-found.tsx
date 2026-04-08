import Link from "next/link";
import Image from "next/image";

export default function NotFound() {
  return (
    <main className="flex flex-col items-center justify-center min-h-screen bg-background text-center px-4">
      <div className="mb-8">
        <Image
          src="/redirect-logo.svg"
          alt="Sad logo"
          width={120}
          height={120}
          priority
        />
      </div>

      <div className="space-y-2 mb-8">
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">
          {"// 404"}
        </p>
        <h1 className="text-foreground font-semibold text-2xl">
          Page not found
        </h1>
        <p className="text-muted text-[1rem]">
          This page doesn&apos;t exist or has been moved.
        </p>
      </div>

      <Link
        href="/"
        className="border border-border bg-transparent hover:bg-surface text-foreground rounded-lg px-6 py-2.5 transition-colors"
      >
        Back to home
      </Link>
    </main>
  );
}

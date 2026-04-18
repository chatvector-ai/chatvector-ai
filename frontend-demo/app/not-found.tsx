import Link from "next/link";
import ErrorState from "./components/ErrorState";

export default function NotFound() {
  return (
    <main className="flex flex-col items-center justify-center min-h-screen bg-background text-center px-4">
      <div className="mb-8">
        <ErrorState
          kicker="// 404"
          heading="Page not found"
          message="This page doesn't exist or has been moved."
          headingLevel="h1"
        />
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

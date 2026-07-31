
export default function BatchResultSkeleton() {
  return (
    <div
      className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 animate-pulse"
      aria-hidden="true"
    >
      {/* title row: status icon + title */}
      <div className="flex items-center gap-2">
        <div className="h-4 w-4 shrink-0 rounded-full bg-border" />
        <div className="h-4 w-1/3 rounded bg-border" />
      </div>

      {/* answer body lines */}
      <div className="flex flex-col gap-2">
        <div className="h-3 w-full rounded bg-border" />
        <div className="h-3 w-full rounded bg-border" />
        <div className="h-3 w-2/3 rounded bg-border" />
      </div>

      {/* metadata / sources area */}
      <div className="mt-auto flex flex-col gap-1 border-t border-border pt-2">
        <div className="h-3 w-1/2 rounded bg-border" />
        <div className="h-3 w-1/4 rounded bg-border" />
      </div>
    </div>
  );
}
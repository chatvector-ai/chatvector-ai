/**
 * Shared skeleton loading primitives for the frontend demo.
 *
 * Domain-specific skeleton layouts (e.g. ChatPageSkeleton) belong in
 * their own component folders and compose these ui/ primitives.
 */

/** A single pulsing rectangle. Accepts Tailwind size/utility classes. */
export function SkeletonBlock({
  className = "",
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`animate-pulse rounded bg-border ${className}`}
      {...props}
    />
  );
}

/** A pulsing circle (avatar placeholder). */
export function SkeletonCircle({
  className = "",
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`animate-pulse rounded-full bg-border ${className}`}
      {...props}
    />
  );
}

/**
 * A bordered surface card that renders its children with a pulse animation.
 * Use this to wrap a group of SkeletonBlocks that form a card-shaped skeleton.
 */
export function SkeletonCard({
  children,
  className = "",
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`animate-pulse rounded-lg border border-border bg-surface ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

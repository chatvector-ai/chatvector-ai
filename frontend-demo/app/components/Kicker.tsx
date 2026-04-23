import { cn } from "@/lib/utils";

const SPACING_CLASSES = {
  sm: "mb-2",
  md: "mb-3",
  lg: "mb-4",
} as const;

interface KickerProps {
  children: React.ReactNode;
  variant?: "comment" | "numbered";
  spacing?: "sm" | "md" | "lg";
  className?: string;
}

export function Kicker({
  children,
  variant = "comment",
  spacing = "md",
  className,
}: KickerProps) {

  const content = variant === "comment" ? `// ${children}` : children;

  return (
    <p
      className={cn(
        "font-mono text-sm uppercase tracking-[2px] text-accent",
        SPACING_CLASSES[spacing],
        className,
      )}
    >
      {content}
    </p>
  );
}

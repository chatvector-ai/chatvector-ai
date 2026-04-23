import { Kicker } from "@/app/components/Kicker";

interface DocPageHeaderProps {
  kicker: string;
  title: string;
  description?: string;
}

export function DocPageHeader({
  kicker,
  title,
  description,
}: DocPageHeaderProps) {
  return (
    <header className="space-y-4">
      <Kicker spacing="sm">{kicker}</Kicker>
      <h1 className="text-3xl font-bold tracking-tight text-foreground">
        {title}
      </h1>
      {description && (
        <p className="text-lg leading-relaxed text-foreground/90">
          {description}
        </p>
      )}
    </header>
  );
}

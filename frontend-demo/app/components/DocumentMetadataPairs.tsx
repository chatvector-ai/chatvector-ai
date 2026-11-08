import {
  formatDocumentMetadataLines,
  type DocumentScalarMetadata,
} from "../lib/documentMetadata";

type Props = {
  metadata?: DocumentScalarMetadata;
  className?: string;
};

export default function DocumentMetadataPairs({ metadata, className }: Props) {
  const lines = formatDocumentMetadataLines(metadata);
  if (lines.length === 0) return null;

  return (
    <div
      className={className ?? "flex flex-wrap gap-x-2 gap-y-0.5"}
      aria-label="Document metadata"
    >
      {lines.map((line) => (
        <span
          key={line}
          className="font-mono text-[10px] text-subtle"
          title={line}
        >
          {line}
        </span>
      ))}
    </div>
  );
}

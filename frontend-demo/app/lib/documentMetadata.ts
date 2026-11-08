export type DocumentScalarMetadata = Record<string, string | number | boolean>;

export function isDocumentScalarMetadata(
  value: unknown,
): value is DocumentScalarMetadata {
  if (value == null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  return Object.entries(value as Record<string, unknown>).every(([key, v]) => {
    if (typeof key !== "string" || key.length === 0) return false;
    return (
      typeof v === "string" ||
      typeof v === "boolean" ||
      (typeof v === "number" && Number.isFinite(v))
    );
  });
}

export function parseDocumentScalarMetadata(
  value: unknown,
): DocumentScalarMetadata | undefined {
  if (!isDocumentScalarMetadata(value)) return undefined;
  return { ...value };
}

export type MetadataRow = { key: string; value: string };

export function parseMetadataValue(raw: string): string | number | boolean {
  const trimmed = raw.trim();
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (
    trimmed !== "" &&
    /^-?\d+(\.\d+)?$/.test(trimmed) &&
    Number.isFinite(Number(trimmed))
  ) {
    return Number(trimmed);
  }
  return trimmed;
}

export function buildMetadataFromRows(
  rows: MetadataRow[],
): DocumentScalarMetadata | undefined {
  const result: DocumentScalarMetadata = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key) continue;
    const valueRaw = row.value.trim();
    if (valueRaw === "") continue;
    result[key] = parseMetadataValue(valueRaw);
  }
  return Object.keys(result).length > 0 ? result : undefined;
}

export function hasEmptyMetadataKey(rows: MetadataRow[]): boolean {
  return rows.some((row) => row.value.trim() !== "" && row.key.trim() === "");
}

export function formatMetadataPair(
  key: string,
  value: string | number | boolean,
): string {
  return `${key}=${String(value)}`;
}

export function formatDocumentMetadataLines(
  metadata: DocumentScalarMetadata | undefined,
): string[] {
  if (!metadata || Object.keys(metadata).length === 0) return [];
  return Object.entries(metadata)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => formatMetadataPair(key, value));
}

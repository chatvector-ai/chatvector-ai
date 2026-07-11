export type BackendErrorField = {
  loc: (string | number)[];
  msg: string;
};

export type ParsedBackendError = {
  code?: string;
  message: string;
  fields?: BackendErrorField[];
};

export class BackendApiError extends Error {
  readonly name = "BackendApiError";

  constructor(
    message: string,
    public readonly parsed: ParsedBackendError,
    public readonly httpStatus?: number
  ) {
    super(message);
  }
}

function parseFields(raw: unknown): BackendErrorField[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const fields: BackendErrorField[] = [];
  for (const item of raw) {
    if (item == null || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const msg = record.msg;
    if (typeof msg !== "string" || msg.length === 0) continue;
    const locRaw = record.loc;
    const loc = Array.isArray(locRaw)
      ? locRaw.filter(
          (part): part is string | number =>
            typeof part === "string" || typeof part === "number"
        )
      : [];
    fields.push({ loc, msg });
  }
  return fields.length > 0 ? fields : undefined;
}

export function formatFieldLocation(loc: (string | number)[]): string {
  const parts = loc.filter((part) => part !== "body");
  if (parts.length === 0) return "request";
  return parts.map(String).join(".");
}

export function parseBackendErrorDetail(detail: unknown): ParsedBackendError {
  if (typeof detail === "string") {
    const trimmed = detail.trim();
    if (trimmed) return { message: trimmed };
  }

  if (detail != null && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    const message =
      typeof record.message === "string" ? record.message.trim() : "";
    const code = typeof record.code === "string" ? record.code : undefined;
    const fields = parseFields(record.fields);

    if (message) {
      return { code, message, fields };
    }
  }

  return { message: "An unexpected error occurred." };
}

export function parseBackendErrorBody(body: unknown): ParsedBackendError {
  if (body != null && typeof body === "object" && "detail" in body) {
    return parseBackendErrorDetail((body as Record<string, unknown>).detail);
  }
  return { message: "An unexpected error occurred." };
}

export function formatBackendErrorMessage(parsed: ParsedBackendError): string {
  const lines = [parsed.message];
  if (parsed.fields?.length) {
    for (const field of parsed.fields) {
      lines.push(`${formatFieldLocation(field.loc)}: ${field.msg}`);
    }
  }
  return lines.join("\n");
}

export function isGenericBackendError(parsed: ParsedBackendError): boolean {
  return (
    parsed.message === "An unexpected error occurred." &&
    !parsed.code &&
    !parsed.fields?.length
  );
}

export async function backendApiErrorFromResponse(
  res: Response,
  fallbackMessage?: string
): Promise<BackendApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error bodies fall back below */
  }

  const parsed = parseBackendErrorBody(body);
  const message = isGenericBackendError(parsed)
    ? fallbackMessage ?? `Server error (${res.status}). Please try again.`
    : formatBackendErrorMessage(parsed);

  return new BackendApiError(message, parsed, res.status);
}

/** Narrows to a plain key-value object, excluding arrays and null. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Returns the value when it is a string, or an empty string otherwise. */
export function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Omits an absent signal for exactOptionalPropertyTypes compatibility. */
export function signalOption(
  signal: AbortSignal | undefined,
): { signal?: AbortSignal } {
  return signal === undefined ? {} : { signal };
}

/** Throws a TypeError when the value is not a non-empty string. */
export function assertRequiredString(
  value: unknown,
  name: string,
): asserts value is string {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${name} must be a non-empty string`);
  }
}

export function cn(
  ...inputs: (string | undefined | null | false | 0 | 0n)[]
): string {
  return inputs.filter(Boolean).join(" ");
}

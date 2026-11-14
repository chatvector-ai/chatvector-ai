export const ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_CODE =
  "anchor_document_excluded_by_filter" as const;

export function mapChatTurnError(
  error: { code: string; message: string },
  activeDocumentFileName?: string,
): { code: string; message: string } {
  if (error.code !== ANCHOR_DOCUMENT_EXCLUDED_BY_FILTER_CODE) {
    return error;
  }
  const name = activeDocumentFileName?.trim();
  if (!name) {
    return error;
  }
  return {
    code: error.code,
    message:
      `The active document (${name}) does not match the metadata filter. ` +
      "Under session scope, the filter can only apply within that document. " +
      "Clear or change the filter in Advanced retrieval and try again.",
  };
}
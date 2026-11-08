import type { AdvancedRetrievalState } from "./advancedRetrieval";
import type { RetrievalScope } from "./retrievalSettings";

export type DocumentIngestionError = {
  stage?: string;
  code?: string;
  message?: string;
};

export function fileTypeFromFileName(fileName: string): string {
  const trimmed = fileName.trim();
  const dot = trimmed.lastIndexOf(".");
  if (dot <= 0 || dot === trimmed.length - 1) {
    return "file";
  }
  return trimmed.slice(dot + 1).toLowerCase();
}

export function documentFailureDetail(
  status: string,
  error: DocumentIngestionError | null | undefined
): string | null {
  if (status !== "failed") return null;
  if (error == null || typeof error !== "object") return null;
  const parts: string[] = [];
  if (typeof error.stage === "string" && error.stage.length > 0) {
    parts.push(error.stage);
  }
  if (typeof error.message === "string" && error.message.length > 0) {
    parts.push(error.message);
  } else if (typeof error.code === "string" && error.code.length > 0) {
    parts.push(error.code);
  }
  return parts.length > 0 ? parts.join(": ") : null;
}

export type ActiveScopeParams = {
  scope: RetrievalScope;
  /** When false, scope may come from env/preset and in-scope membership is unknown. */
  scopeIsExplicit: boolean;
  selectedDocumentId: string | null;
  documentId: string;
  status: string;
};

/** False when scope comes from a preset and the user has not set scope explicitly. */
export function isRetrievalScopeMembershipDefinite(
  state: AdvancedRetrievalState
): boolean {
  const preset = state.explicit.preset;
  return !(preset !== undefined && state.explicit.scope === undefined);
}

/** null means active-scope membership is not known (e.g. scope follows a preset). */
export function isDocumentInActiveScope(params: ActiveScopeParams): boolean | null {
  if (!params.scopeIsExplicit) {
    return null;
  }
  if (params.scope === "tenant") {
    return params.status === "completed";
  }
  if (params.selectedDocumentId === null) {
    return false;
  }
  return params.documentId === params.selectedDocumentId;
}

export type SessionDocumentListRow<T> =
  | {
      kind: "summary";
      documentId: string;
      summary: T;
    }
  | {
      kind: "unavailable";
      documentId: string;
    };

export function sessionDocumentRows<T extends { document_id: string }>(
  sessionDocumentIds: string[],
  summaries: T[]
): SessionDocumentListRow<T>[] {
  const byId = new Map(summaries.map((doc) => [doc.document_id, doc]));
  return sessionDocumentIds.map((documentId) => {
    const summary = byId.get(documentId);
    if (summary) {
      return { kind: "summary", documentId, summary };
    }
    return { kind: "unavailable", documentId };
  });
}

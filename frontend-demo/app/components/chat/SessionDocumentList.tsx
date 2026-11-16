"use client";

import DocumentListRow from "../DocumentListRow";
import type { AdvancedRetrievalState } from "../../lib/advancedRetrieval";
import { effectiveScope } from "../../lib/advancedRetrieval";
import type { AttachmentState } from "../../lib/api";
import {
  documentFailureDetail,
  fileTypeFromFileName,
  isDocumentInActiveScope,
  isRetrievalScopeMembershipDefinite,
  sessionDocumentRows,
} from "../../lib/documentListDisplay";
import type { DocumentSummary } from "../../lib/api";

type Props = {
  sessionDocumentIds: string[];
  documentSummaries: DocumentSummary[];
  retrievalState: AdvancedRetrievalState;
  attachment: AttachmentState | null;
  activeDocumentId?: string | null;
  onMakeActive?: (documentId: string) => void;
  onReplace: (documentId: string) => void;
  onDelete: (documentId: string) => void;
  actionsDisabled?: boolean;
};

export default function SessionDocumentList({
  sessionDocumentIds,
  documentSummaries,
  retrievalState,
  attachment,
  activeDocumentId,
  onMakeActive,
  onReplace,
  onDelete,
  actionsDisabled = false,
}: Props) {
  const rows = sessionDocumentRows(sessionDocumentIds, documentSummaries);
  if (rows.length === 0) {
    return null;
  }

  const scope = effectiveScope(retrievalState);
  const scopeIsExplicit = isRetrievalScopeMembershipDefinite(retrievalState);
  const selectedDocumentId = activeDocumentId ?? attachment?.documentId ?? null;
  const hasMultipleDocuments = rows.length > 1;

  const headingText =
    scope === "session" && hasMultipleDocuments
      ? "Session documents — only the active document is searched"
      : "Session documents";

  return (
    <div className="px-4 pb-2" data-testid="session-document-list">
      <p className="mb-2 text-xs font-medium text-muted">{headingText}</p>
      <ul className="flex flex-col gap-2">
        {rows.map((row) => {
          if (row.kind === "unavailable") {
            return (
              <li key={row.documentId}>
                <DocumentListRow
                  documentId={row.documentId}
                  fileName=""
                  fileType="file"
                  status="unavailable"
                  failureDetail={null}
                  unavailable
                />
              </li>
            );
          }

          const { summary } = row;
          const processing =
            summary.status !== "completed" && summary.status !== "failed";
          const inActiveScope = isDocumentInActiveScope({
            scope,
            scopeIsExplicit,
            selectedDocumentId,
            documentId: summary.document_id,
            status: summary.status,
            hasMultipleDocuments,
          });

          const isActive = summary.document_id === selectedDocumentId;
          const onRowMakeActive =
            !isActive && onMakeActive
              ? () => onMakeActive(summary.document_id)
              : undefined;

          return (
            <li key={summary.document_id}>
              <DocumentListRow
                documentId={summary.document_id}
                fileName={summary.file_name}
                fileType={fileTypeFromFileName(summary.file_name)}
                status={summary.status}
                failureDetail={documentFailureDetail(
                  summary.status,
                  summary.error
                )}
                metadata={summary.metadata}
                inActiveScope={inActiveScope}
                isActive={isActive}
                onMakeActive={onRowMakeActive}
                onReplace={
                  processing ? undefined : () => onReplace(summary.document_id)
                }
                onDelete={() => onDelete(summary.document_id)}
                disabled={actionsDisabled}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

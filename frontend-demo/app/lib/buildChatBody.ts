import { getSessionId } from "./session";
import type { AdvancedRetrievalState } from "./advancedRetrieval";
import { clampMatchCount } from "./retrievalSettings";

export type BuildChatBodyInput = {
  question: string;
  docId: string;
  sessionId?: string | null;
  debugRetrieval?: boolean;
  retrieval: AdvancedRetrievalState;
};

export function buildChatRequestBody(
  input: BuildChatBodyInput
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    question: input.question,
    doc_id: input.docId,
  };

  const sessionId =
    input.sessionId !== undefined ? input.sessionId : getSessionId();
  if (sessionId !== null) {
    body.session_id = sessionId;
  }

  const ex = input.retrieval.explicit;

  if (ex.scope !== undefined) {
    body.scope = ex.scope;
  }
  if (ex.matchCount !== undefined) {
    body.match_count = clampMatchCount(ex.matchCount);
  }
  if (ex.hybridEnabled !== undefined) {
    body.hybrid_enabled = ex.hybridEnabled;
  }
  if (ex.rerankingEnabled !== undefined) {
    body.reranking_enabled = ex.rerankingEnabled;
  }
  if (ex.rerankerProvider !== undefined) {
    body.reranker_provider = ex.rerankerProvider;
  }
  if (ex.queryTransformationEnabled !== undefined) {
    body.query_transformation_enabled = ex.queryTransformationEnabled;
  }
  if (ex.queryTransformationStrategy !== undefined) {
    body.query_transformation_strategy = ex.queryTransformationStrategy;
  }
  if (
    ex.metadataFilter !== undefined &&
    Object.keys(ex.metadataFilter).length > 0
  ) {
    body.metadata_filter = ex.metadataFilter;
  }

  const history: Record<string, unknown> = {};
  if (ex.historyAwareRetrieval !== undefined) {
    history.history_aware_retrieval = ex.historyAwareRetrieval;
  }
  if (ex.retrievalHistoryWindow !== undefined) {
    history.retrieval_history_window = ex.retrievalHistoryWindow;
  }
  if (ex.generationHistoryWindow !== undefined) {
    history.generation_history_window = ex.generationHistoryWindow;
  }
  if (Object.keys(history).length > 0) {
    body.history = history;
  }

  if (ex.preset !== undefined) {
    body.retrieval = { preset: ex.preset };
  }

  if (input.debugRetrieval === true) {
    body.debug_retrieval = true;
  }

  return body;
}

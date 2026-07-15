export const DOCUMENT_ID = "11111111-1111-4111-8111-111111111111";
export const SECOND_DOCUMENT_ID = "22222222-2222-4222-8222-222222222222";
export const SESSION_ID = "session-1";

export const uploadAcceptedPayload = {
  message: "Accepted",
  document_id: DOCUMENT_ID,
  status: "queued",
  queue_position: 2,
  status_endpoint: `/documents/${DOCUMENT_ID}/status`,
  future_upload_field: "kept in raw",
};

export const queuedStatusPayload = {
  document_id: DOCUMENT_ID,
  status: "queued",
  chunks: { total: 0, processed: 0 },
  created_at: "2026-07-14 10:00:00",
  updated_at: "2026-07-14 10:00:01",
  queue_position: 2,
  future_status_field: { trace: "abc" },
};

export const completedStatusPayload = {
  document_id: DOCUMENT_ID,
  status: "completed",
  chunks: { total: 3, processed: 3 },
  created_at: "2026-07-14 10:00:00",
  updated_at: "2026-07-14 10:00:04",
};

export const failedStatusPayload = {
  document_id: DOCUMENT_ID,
  status: "failed",
  chunks: { total: 3, processed: 0 },
  created_at: "2026-07-14 10:00:00",
  updated_at: "2026-07-14 10:00:04",
  error: {
    stage: "embedding",
    code: "provider_timeout",
    message: "Embedding provider timed out.",
  },
};

export const chatOkPayload = {
  question: "What is this document about?",
  doc_id: DOCUMENT_ID,
  chunks: 2,
  answer: "It is an onboarding guide.",
  sources: [
    {
      file_name: "guide.pdf",
      page_number: 1,
      chunk_index: 0,
      score: 0.95,
      score_type: "hybrid_rrf",
    },
    {
      file_name: null,
      page_number: null,
      chunk_index: null,
      score: null,
      score_type: null,
    },
  ],
  latency_ms: 312,
  model: "gpt-test",
  status: "ok",
  retrieval_debug: { candidates: 8 },
};

export const chatSoftErrorPayload = {
  question: "What is this document about?",
  doc_id: DOCUMENT_ID,
  chunks: 0,
  answer: "",
  sources: [],
  latency_ms: 0,
  model: "",
  status: "error",
  error: {
    code: "no_documents_in_scope",
    message: "No documents available for retrieval in the requested scope.",
  },
};

export const batchPartialPayload = {
  count: 2,
  success_count: 1,
  failure_count: 1,
  results: [
    {
      status: "ok",
      question: "Summarize it.",
      doc_ids: [DOCUMENT_ID],
      chunks: 1,
      answer: "Summary",
      sources: [
        {
          file_name: "guide.pdf",
          page_number: 2,
          chunk_index: 1,
          score: 0.8,
          score_type: "vector",
        },
      ],
      latency_ms: 123,
      model: "gpt-test",
      session_id: "generated-session-kept-in-raw",
    },
    {
      status: "error",
      question: "What failed?",
      doc_ids: [SECOND_DOCUMENT_ID],
      chunks: 0,
      error: {
        code: "query_processing_failed",
        message: "An error occurred processing this query.",
      },
    },
  ],
  future_batch_field: true,
};

export const sessionPayload = {
  id: SESSION_ID,
  tenant_id: "tenant-1",
  created_at: "2026-07-14T10:00:00+00:00",
  last_active: "2026-07-14T10:01:00+00:00",
  metadata: { source: "sdk" },
  document_ids: [DOCUMENT_ID],
  future_session_field: "kept in raw",
};

export const secondSessionPayload = {
  id: "session-2",
  tenant_id: null,
  created_at: "2026-07-14T11:00:00+00:00",
  last_active: "2026-07-14T11:01:00+00:00",
  metadata: {},
  document_ids: [],
};

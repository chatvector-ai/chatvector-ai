import { iterChatStreamEvents } from "../internal/sse.js";
import type {
  BatchChatQuery,
  BatchChatRequest,
  BatchChatResponse,
  BatchChatResult,
  ChatRequest,
  ChatResponse,
  ChatSource,
  ChatStreamEvent,
  RequestOptions,
  RetrievalDebugMetadata,
} from "../models.js";
import { HttpClient } from "../internal/http.js";
import {
  applyRequestConfigFields,
  validateMatchCount,
} from "../internal/request-config.js";
import {
  assertRequiredString,
  isRecord,
  signalOption,
  stringValue,
} from "../internal/utils.js";

export class ChatsResource {
  constructor(private readonly http: HttpClient) {}

  async chat(
    request: ChatRequest,
    options: RequestOptions = {},
  ): Promise<ChatResponse> {
    assertRequiredString(request?.question, "question");
    assertRequiredString(request?.docId, "docId");
    const body: Record<string, unknown> = {
      question: request.question,
      doc_id: request.docId,
    };
    if (request.matchCount !== undefined) {
      validateMatchCount(request.matchCount);
      body.match_count = request.matchCount;
    }
    addOptional(body, "session_id", request.sessionId);
    addOptional(body, "scope", request.scope);
    if (request.debugRetrieval === true) {
      body.debug_retrieval = true;
    }
    applyRequestConfigFields(body, request.retrieval, request.history);

    const payload = await this.http.requestJson("POST", "/chat", {
      json: body,
      ...signalOption(options.signal),
    });
    return mapChatResponse(payload);
  }

  async batchChat(
    request: BatchChatRequest,
    options: RequestOptions = {},
  ): Promise<BatchChatResponse> {
    // Single-document batch items are compare-style: no session history injection
    // and no turn persistence, even when sessionId is set on the item or request.
    if (!request || !Array.isArray(request.queries)) {
      throw new TypeError("queries must be an array");
    }
    const body: Record<string, unknown> = {
      queries: request.queries.map(serializeBatchQuery),
    };
    addOptional(body, "session_id", request.sessionId);
    addOptional(body, "scope", request.scope);
    if (request.debugRetrieval === true) {
      body.debug_retrieval = true;
    }
    applyRequestConfigFields(body, request.retrieval, request.history);

    const payload = await this.http.requestJson("POST", "/chat/batch", {
      json: body,
      ...signalOption(options.signal),
    });
    return mapBatchResponse(payload);
  }

  streamChat(
    request: ChatRequest,
    options: RequestOptions = {},
  ): AsyncIterable<ChatStreamEvent> {
    return this.iterStreamChat(request, options);
  }

  private async *iterStreamChat(
    request: ChatRequest,
    options: RequestOptions = {},
  ): AsyncGenerator<ChatStreamEvent> {
    assertRequiredString(request?.question, "question");
    assertRequiredString(request?.docId, "docId");
    const body: Record<string, unknown> = {
      question: request.question,
      doc_id: request.docId,
    };
    if (request.matchCount !== undefined) {
      validateMatchCount(request.matchCount);
      body.match_count = request.matchCount;
    }
    addOptional(body, "session_id", request.sessionId);
    addOptional(body, "scope", request.scope);
    if (request.debugRetrieval === true) {
      body.debug_retrieval = true;
    }
    applyRequestConfigFields(body, request.retrieval, request.history);

    const response = await this.http.openStream("POST", "/chat/stream", {
      json: body,
      ...signalOption(options.signal),
    });

    try {
      const streamOptions: { signal?: AbortSignal; apiKey?: string } = {};
      const apiKey = this.http.configuredApiKey();
      if (apiKey !== undefined) {
        streamOptions.apiKey = apiKey;
      }
      if (options.signal !== undefined) {
        streamOptions.signal = options.signal;
      }
      yield* iterChatStreamEvents(response, streamOptions);
    } finally {
      try {
        await response.body?.cancel();
      } catch {
        // Body cancellation failures are not authoritative for callers.
      }
    }
  }
}

function serializeBatchQuery(query: BatchChatQuery): Record<string, unknown> {
  assertRequiredString(query?.question, "query.question");
  if (!Array.isArray(query.docIds)) {
    throw new TypeError("query.docIds must be an array");
  }
  const payload: Record<string, unknown> = {
    question: query.question,
    doc_ids: [...query.docIds],
  };
  if (query.matchCount !== undefined) {
    validateMatchCount(query.matchCount);
    payload.match_count = query.matchCount;
  }
  addOptional(payload, "session_id", query.sessionId);
  addOptional(payload, "scope", query.scope);
  applyRequestConfigFields(payload, query.retrieval, query.history);
  return payload;
}

function mapChatResponse(payload: Record<string, unknown>): ChatResponse {
  const result: ChatResponse = {
    question: stringValue(payload.question),
    docId: stringValue(payload.doc_id),
    chunks: numberValue(payload.chunks),
    answer: stringValue(payload.answer),
    sources: mapSources(payload.sources),
    latencyMs: numberValue(payload.latency_ms),
    model: stringValue(payload.model),
    status: payload.status === "error" ? "error" : "ok",
    _raw: payload,
  };
  if (typeof payload.session_id === "string") result.sessionId = payload.session_id;
  const retrievalDebug = mapRetrievalDebug(payload.retrieval_debug);
  if (retrievalDebug !== undefined) result.retrievalDebug = retrievalDebug;
  const error = mapSoftError(payload.error);
  if (error) result.error = error;
  return result;
}

function mapBatchResponse(payload: Record<string, unknown>): BatchChatResponse {
  const results = Array.isArray(payload.results)
    ? payload.results.filter(isRecord).map(mapBatchResult)
    : [];
  return {
    count: numberValue(payload.count, results.length),
    successCount: numberValue(payload.success_count),
    failureCount: numberValue(payload.failure_count),
    results,
    _raw: payload,
  };
}

function mapBatchResult(payload: Record<string, unknown>): BatchChatResult {
  const result: BatchChatResult = {
    status: payload.status === "error" ? "error" : "ok",
    question: stringValue(payload.question),
    docIds: stringArray(payload.doc_ids),
    chunks: numberValue(payload.chunks),
    latencyMs: numberValue(payload.latency_ms),
    model: stringValue(payload.model),
    _raw: payload,
  };
  if (typeof payload.answer === "string") result.answer = payload.answer;
  if (Array.isArray(payload.sources)) result.sources = mapSources(payload.sources);
  if (typeof payload.session_id === "string") result.sessionId = payload.session_id;
  const retrievalDebug = mapRetrievalDebug(payload.retrieval_debug);
  if (retrievalDebug !== undefined) result.retrievalDebug = retrievalDebug;
  const error = mapSoftError(payload.error);
  if (error) result.error = error;
  return result;
}

function mapSources(value: unknown): ChatSource[] {
  return Array.isArray(value)
    ? value.filter(isRecord).map((source) => mapChatSource(source))
    : [];
}

function mapChatSource(source: Record<string, unknown>): ChatSource {
  const result: ChatSource = {
    fileName: nullableString(source.file_name),
    pageNumber: nullableNumber(source.page_number),
    pageEnd: nullableNumber(source.page_end),
    chunkIndex: nullableNumber(source.chunk_index),
  };
  if (source.score === null || typeof source.score === "number") {
    result.score = source.score;
  }
  if (source.score_type === null || typeof source.score_type === "string") {
    result.scoreType = source.score_type;
  }
  assignNullableNumber(result, "vectorScore", source.vector_score);
  assignNullableNumber(result, "fullTextScore", source.full_text_score);
  assignNullableNumber(result, "rrfScore", source.rrf_score);
  assignNullableNumber(result, "rerankerScore", source.reranker_score);
  assignNullableNumber(result, "rerankOrder", source.rerank_order);
  return result;
}

function mapRetrievalDebug(
  value: unknown,
): RetrievalDebugMetadata | undefined {
  if (!isRecord(value)) {
    return undefined;
  }
  const result: RetrievalDebugMetadata = { ...value };
  if (typeof value.original_query === "string") {
    result.originalQuery = value.original_query;
  }
  if (Array.isArray(value.transformed_queries)) {
    result.transformedQueries = value.transformed_queries.filter(
      (item): item is string => typeof item === "string",
    );
  }
  if (typeof value.transformation_strategy === "string") {
    result.transformationStrategy = value.transformation_strategy;
  }
  if (typeof value.effective_retrieval_query === "string") {
    result.effectiveRetrievalQuery = value.effective_retrieval_query;
  }
  if (isRecord(value.timing_ms)) {
    result.timingMs = value.timing_ms as Record<string, number>;
  }
  if (isRecord(value.effective_config)) {
    result.effectiveConfig = value.effective_config;
  }
  return result;
}

function assignNullableNumber(
  target: ChatSource,
  key:
    | "vectorScore"
    | "fullTextScore"
    | "rrfScore"
    | "rerankerScore"
    | "rerankOrder",
  value: unknown,
): void {
  if (value === null || (typeof value === "number" && Number.isFinite(value))) {
    target[key] = value;
  }
}

function mapSoftError(
  value: unknown,
): { code: string; message: string } | undefined {
  return isRecord(value)
    ? {
        code: stringValue(value.code),
        message: stringValue(value.message),
      }
    : undefined;
}

function addOptional(
  target: Record<string, unknown>,
  key: string,
  value: unknown,
): void {
  if (value !== undefined) target[key] = value;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

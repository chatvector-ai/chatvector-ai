import type {
  BatchChatQuery,
  BatchChatRequest,
  BatchChatResponse,
  BatchChatResult,
  ChatRequest,
  ChatResponse,
  ChatSource,
  RequestOptions,
} from "../models.js";
import { HttpClient } from "../internal/http.js";
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
    addOptional(body, "match_count", request.matchCount);
    addOptional(body, "session_id", request.sessionId);
    addOptional(body, "scope", request.scope);

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
    if (!request || !Array.isArray(request.queries)) {
      throw new TypeError("queries must be an array");
    }
    const body: Record<string, unknown> = {
      queries: request.queries.map(serializeBatchQuery),
    };
    addOptional(body, "session_id", request.sessionId);
    addOptional(body, "scope", request.scope);

    const payload = await this.http.requestJson("POST", "/chat/batch", {
      json: body,
      ...signalOption(options.signal),
    });
    return mapBatchResponse(payload);
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
  addOptional(payload, "match_count", query.matchCount);
  addOptional(payload, "session_id", query.sessionId);
  addOptional(payload, "scope", query.scope);
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
  const error = mapSoftError(payload.error);
  if (error) result.error = error;
  return result;
}

function mapSources(value: unknown): ChatSource[] {
  return Array.isArray(value)
    ? value.filter(isRecord).map((source) => {
        const result: ChatSource = {
          fileName: nullableString(source.file_name),
          pageNumber: nullableNumber(source.page_number),
          chunkIndex: nullableNumber(source.chunk_index),
        };
        if (source.score === null || typeof source.score === "number") {
          result.score = source.score;
        }
        if (source.score_type === null || typeof source.score_type === "string") {
          result.scoreType = source.score_type;
        }
        return result;
      })
    : [];
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

import {
  ChatVectorAPIError,
  ChatVectorTimeoutError,
  isChatVectorError,
} from "../errors.js";
import {
  runBulkUploads,
  type UploadManyItem,
  type UploadManyWorkerOptions,
} from "../internal/bulk-upload.js";
import { collectDirectoryUploadPaths } from "../internal/directory-upload.js";
import type {
  BulkUploadSummary,
  DocumentListResponse,
  DocumentResponse,
  DocumentStatus,
  DocumentSummary,
  RequestOptions,
  UploadDirectoryOptions,
  UploadInput,
  UploadManyOptions,
  WaitForReadyOptions,
} from "../models.js";
import { iterDocumentStatusEvents } from "../internal/sse.js";
import { HttpClient } from "../internal/http.js";
import {
  abortReason,
  systemClock,
  throwIfAborted,
  type Clock,
} from "../internal/time.js";
import { createUploadFormData } from "../internal/upload.js";
import {
  assertRequiredString,
  isRecord,
  signalOption,
  stringValue,
} from "../internal/utils.js";

const DEFAULT_WAIT_TIMEOUT_MS = 60_000;
const DEFAULT_POLL_INTERVAL_MS = 2_000;

export class DocumentsResource {
  constructor(
    private readonly http: HttpClient,
    private readonly clock: Clock = systemClock,
  ) {}

  async uploadDocument(
    input: UploadInput,
    options: RequestOptions = {},
  ): Promise<DocumentResponse> {
    throwIfAborted(options.signal);
    const ingestBody = await createUploadFormData(input);
    const uploadHeaders = uploadSessionHeaders(input);

    try {
      const payload = await this.http.requestJson("POST", "/ingest", {
        body: ingestBody,
        ...(uploadHeaders === undefined ? {} : { headers: uploadHeaders }),
        ...signalOption(options.signal),
      });
      return mapDocumentResponse(payload);
    } catch (error) {
      if (options.signal?.aborted) {
        throw abortReason(options.signal);
      }
      if (
        !isChatVectorError(error) ||
        error.statusCode !== 404 ||
        options.signal?.aborted
      ) {
        throw error;
      }
    }

    throwIfAborted(options.signal);
    const uploadBody = await createUploadFormData(input);
    const payload = await this.http.requestJson("POST", "/upload", {
      body: uploadBody,
      ...(uploadHeaders === undefined ? {} : { headers: uploadHeaders }),
      ...signalOption(options.signal),
    });
    return mapDocumentResponse(payload);
  }

  async uploadMany(
    items: readonly UploadManyItem[],
    options: UploadManyOptions = {},
  ): Promise<BulkUploadSummary> {
    throwIfAborted(options.signal);
    const sessionId = options.sessionId?.trim();
    return runBulkUploads(
      items,
      async (input, signal) => {
        const withSession =
          sessionId === undefined || sessionId === ""
            ? input
            : { ...input, sessionId };
        return this.uploadDocument(withSession, signalOption(signal));
      },
      async (documentId, signal, timeoutMs, pollIntervalMs) => {
        await this.waitForReady(documentId, {
          ...signalOption(signal),
          ...(timeoutMs === undefined ? {} : { timeoutMs }),
          ...(pollIntervalMs === undefined ? {} : { pollIntervalMs }),
        });
      },
      buildUploadManyWorkerOptions(options),
    );
  }

  async uploadDirectory(
    directoryPath: string,
    options: UploadDirectoryOptions = {},
  ): Promise<BulkUploadSummary> {
    throwIfAborted(options.signal);
    const paths = await collectDirectoryUploadPaths(directoryPath, {
      ...(options.pattern === undefined ? {} : { pattern: options.pattern }),
      ...(options.recursive === undefined ? {} : { recursive: options.recursive }),
    });
    return this.uploadMany(paths, options);
  }

  async listDocuments(
    options: RequestOptions = {},
  ): Promise<DocumentListResponse> {
    const payload = await this.http.requestJson("GET", "/documents", {
      ...signalOption(options.signal),
    });
    const documents = Array.isArray(payload.documents)
      ? payload.documents.filter(isRecord).map(mapDocumentSummary)
      : [];
    return {
      tenantId: stringValue(payload.tenant_id),
      documents,
      _raw: payload,
    };
  }

  async deleteDocument(
    documentId: string,
    options: RequestOptions = {},
  ): Promise<void> {
    assertRequiredString(documentId, "documentId");
    await this.http.requestVoid(
      "DELETE",
      `/documents/${encodeURIComponent(documentId)}`,
      signalOption(options.signal),
    );
  }

  streamDocumentStatus(
    documentId: string,
    options: RequestOptions = {},
  ): AsyncIterable<DocumentStatus> {
    return this.iterDocumentStatus(documentId, options);
  }

  private async *iterDocumentStatus(
    documentId: string,
    options: RequestOptions = {},
  ): AsyncGenerator<DocumentStatus> {
    assertRequiredString(documentId, "documentId");
    const response = await this.http.openStream(
      "GET",
      `/documents/${encodeURIComponent(documentId)}/status/stream`,
      signalOption(options.signal),
    );

    try {
      const streamOptions: { signal?: AbortSignal } = {};
      if (options.signal !== undefined) {
        streamOptions.signal = options.signal;
      }
      yield* iterDocumentStatusEvents(response, streamOptions);
    } finally {
      try {
        await response.body?.cancel();
      } catch {
        // Body cancellation failures are not authoritative for callers.
      }
    }
  }

  async getDocumentStatus(
    documentId: string,
    options: RequestOptions = {},
  ): Promise<DocumentStatus> {
    assertRequiredString(documentId, "documentId");
    const payload = await this.http.requestJson(
      "GET",
      `/documents/${encodeURIComponent(documentId)}/status`,
      signalOption(options.signal),
    );
    return mapDocumentStatus(payload);
  }

  async waitForReady(
    documentId: string,
    options: WaitForReadyOptions = {},
  ): Promise<DocumentStatus> {
    assertRequiredString(documentId, "documentId");
    const timeoutMs = options.timeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS;
    const pollIntervalMs =
      options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
    assertPositiveFinite(timeoutMs, "timeoutMs");
    assertPositiveFinite(pollIntervalMs, "pollIntervalMs");
    throwIfAborted(options.signal);

    const deadline = this.clock.now() + timeoutMs;
    const controller = new AbortController();
    let deadlineExpired = false;
    let lastStatus: DocumentStatus | undefined;
    const onAbort = (): void => {
      controller.abort(
        options.signal === undefined
          ? abortError()
          : abortReason(options.signal),
      );
    };
    options.signal?.addEventListener("abort", onAbort, { once: true });
    if (options.signal?.aborted) {
      onAbort();
    }
    const timer = setTimeout(() => {
      deadlineExpired = true;
      controller.abort(new DOMException("Polling timed out", "TimeoutError"));
    }, timeoutMs);

    try {
      while (true) {
        if (this.clock.now() >= deadline) {
          throw waitTimeoutError(documentId, timeoutMs, lastStatus);
        }
        lastStatus = mapDocumentStatus(
          await this.http.requestJson(
            "GET",
            `/documents/${encodeURIComponent(documentId)}/status`,
            { signal: controller.signal, deadlineMs: deadline },
          ),
        );
        // A replacement keeps `status` completed/failed while it runs, so only
        // `statusDetail` says whether the latest content is ready yet.
        const replacing = lastStatus.statusDetail === "replacement_in_progress";
        const replacementFailed =
          lastStatus.statusDetail === "replacement_failed";
        if (
          !replacing &&
          !replacementFailed &&
          lastStatus.status === "completed"
        ) {
          return lastStatus;
        }
        if (!replacing && (replacementFailed || lastStatus.status === "failed")) {
          const backendMessage =
            isRecord(lastStatus.error) &&
            typeof lastStatus.error.message === "string"
              ? ` ${lastStatus.error.message}`
              : "";
          throw new ChatVectorAPIError(
            `Document '${documentId}' ${replacementFailed ? "replacement" : "processing"} failed.${backendMessage}`,
            {
              code: "document_failed",
              details: lastStatus,
            },
          );
        }

        const remainingMs = deadline - this.clock.now();
        if (remainingMs <= 0) {
          throw waitTimeoutError(documentId, timeoutMs, lastStatus);
        }
        await this.clock.sleep(
          Math.min(pollIntervalMs, remainingMs),
          controller.signal,
        );
      }
    } catch (error) {
      if (options.signal?.aborted) {
        throw abortReason(options.signal);
      }
      if (deadlineExpired || this.clock.now() >= deadline) {
        throw waitTimeoutError(documentId, timeoutMs, lastStatus);
      }
      throw error;
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }
  }
}

function waitTimeoutError(
  documentId: string,
  timeoutMs: number,
  lastStatus: DocumentStatus | undefined,
): ChatVectorTimeoutError {
  const options = {
    statusCode: 408,
    ...(lastStatus === undefined ? {} : { details: lastStatus }),
  };
  return new ChatVectorTimeoutError(
    `Timed out after ${timeoutMs}ms while waiting for document '${documentId}'.`,
    options,
  );
}

function buildUploadManyWorkerOptions(
  options: UploadManyOptions,
): UploadManyWorkerOptions {
  return {
    ...(options.concurrency === undefined
      ? {}
      : { concurrency: options.concurrency }),
    ...(options.failFast === undefined ? {} : { failFast: options.failFast }),
    ...(options.retryOnRateLimit === undefined
      ? {}
      : { retryOnRateLimit: options.retryOnRateLimit }),
    ...(options.maxRateLimitRetries === undefined
      ? {}
      : { maxRateLimitRetries: options.maxRateLimitRetries }),
    ...(options.idempotencyKeyForPath === undefined
      ? {}
      : { idempotencyKeyForPath: options.idempotencyKeyForPath }),
    ...(options.onProgress === undefined ? {} : { onProgress: options.onProgress }),
    ...(options.waitForReady === undefined
      ? {}
      : { waitForReady: options.waitForReady }),
    ...(options.waitForReadyTimeoutMs === undefined
      ? {}
      : { waitForReadyTimeoutMs: options.waitForReadyTimeoutMs }),
    ...(options.waitForReadyPollIntervalMs === undefined
      ? {}
      : { waitForReadyPollIntervalMs: options.waitForReadyPollIntervalMs }),
    ...signalOption(options.signal),
  };
}

function uploadSessionHeaders(
  input: UploadInput,
): Record<string, string> | undefined {
  const headers: Record<string, string> = {};
  const sessionId = input.sessionId?.trim();
  if (sessionId) {
    headers["X-Session-Id"] = sessionId;
  }
  const idempotencyKey = input.idempotencyKey?.trim();
  if (idempotencyKey) {
    headers["Idempotency-Key"] = idempotencyKey;
  }
  return Object.keys(headers).length > 0 ? headers : undefined;
}

function mapDocumentSummary(
  payload: Record<string, unknown>,
): DocumentSummary {
  const result: DocumentSummary = {
    documentId: stringValue(payload.document_id),
    fileName:
      payload.file_name === null || typeof payload.file_name === "string"
        ? payload.file_name
        : null,
    status: stringValue(payload.status),
    _raw: payload,
  };
  if (typeof payload.status_detail === "string") {
    result.statusDetail = payload.status_detail;
  }
  if (payload.created_at === null || typeof payload.created_at === "string") {
    result.createdAt = payload.created_at;
  }
  if (payload.updated_at === null || typeof payload.updated_at === "string") {
    result.updatedAt = payload.updated_at;
  }
  return result;
}

function mapDocumentResponse(
  payload: Record<string, unknown>,
): DocumentResponse {
  const result: DocumentResponse = {
    documentId: stringValue(payload.document_id),
    status: stringValue(payload.status),
    _raw: payload,
  };
  if (typeof payload.message === "string") result.message = payload.message;
  if (typeof payload.queue_position === "number") {
    result.queuePosition = payload.queue_position;
  }
  if (typeof payload.status_endpoint === "string") {
    result.statusEndpoint = payload.status_endpoint;
  }
  if (typeof payload.status_detail === "string") {
    result.statusDetail = payload.status_detail;
  }
  return result;
}

function mapDocumentStatus(
  payload: Record<string, unknown>,
): DocumentStatus {
  const result: DocumentStatus = {
    documentId: stringValue(payload.document_id),
    status: stringValue(payload.status),
    _raw: payload,
  };
  if (payload.chunks === null || isRecord(payload.chunks)) {
    result.chunks = payload.chunks;
  }
  if (payload.created_at === null || typeof payload.created_at === "string") {
    result.createdAt = payload.created_at;
  }
  if (payload.updated_at === null || typeof payload.updated_at === "string") {
    result.updatedAt = payload.updated_at;
  }
  if (payload.error === null || isRecord(payload.error)) {
    result.error = payload.error;
  }
  if (typeof payload.queue_position === "number") {
    result.queuePosition = payload.queue_position;
  }
  if (typeof payload.status_detail === "string") {
    result.statusDetail = payload.status_detail;
  }
  if (payload.job === null || isRecord(payload.job)) {
    result.job = payload.job;
  }
  if (isRecord(payload.metadata)) {
    result.metadata = payload.metadata;
  }
  if (payload.file_name === null || typeof payload.file_name === "string") {
    result.fileName = payload.file_name;
  }
  return result;
}

function assertPositiveFinite(value: number, name: string): void {
  if (!Number.isFinite(value) || value <= 0) {
    throw new RangeError(`${name} must be a positive finite number`);
  }
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted", "AbortError");
}

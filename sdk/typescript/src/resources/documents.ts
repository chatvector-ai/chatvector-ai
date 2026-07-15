import {
  ChatVectorAPIError,
  ChatVectorTimeoutError,
  isChatVectorError,
} from "../errors.js";
import type {
  DocumentResponse,
  DocumentStatus,
  RequestOptions,
  UploadInput,
  WaitForReadyOptions,
} from "../models.js";
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

    try {
      const payload = await this.http.requestJson("POST", "/ingest", {
        body: ingestBody,
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
      ...signalOption(options.signal),
    });
    return mapDocumentResponse(payload);
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
        if (lastStatus.status === "completed") {
          return lastStatus;
        }
        if (lastStatus.status === "failed") {
          const backendMessage =
            isRecord(lastStatus.error) &&
            typeof lastStatus.error.message === "string"
              ? ` ${lastStatus.error.message}`
              : "";
          throw new ChatVectorAPIError(
            `Document '${documentId}' processing failed.${backendMessage}`,
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

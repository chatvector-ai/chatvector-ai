import multipart from "@fastify/multipart";
import Fastify, {
  type FastifyReply,
  type FastifyRequest,
} from "fastify";
import {
  ChatVectorAPIError,
  ChatVectorClient,
  ChatVectorRateLimitError,
  ChatVectorTimeoutError,
  type ChatRequest,
} from "@chatvector/sdk";

declare module "fastify" {
  interface FastifyRequest {
    appUserId: string;
  }
}

function requiredEnvironmentVariable(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} must be set in the server environment`);
  }
  return value;
}

const chatVector = new ChatVectorClient({
  baseUrl: requiredEnvironmentVariable("CHATVECTOR_BASE_URL"),
  apiKey: requiredEnvironmentVariable("CHATVECTOR_API_KEY"),
  timeoutMs: 30_000,
});

const server = Fastify({ logger: true });

await server.register(multipart, {
  limits: {
    files: 1,
    fileSize: 25 * 1024 * 1024,
  },
});

server.decorateRequest("appUserId", "");

// This header is only a compact stand-in for the application's own verified
// session/JWT. It is never used as ChatVector authentication or forwarded as
// the ChatVector bearer token.
server.addHook("preHandler", async (request, reply) => {
  if (!request.url.startsWith("/api/")) return;

  const userId = request.headers["x-user-id"];
  if (typeof userId !== "string" || userId.trim() === "") {
    await reply.code(401).send({
      error: {
        code: "application_auth_required",
        message: "Authenticate with the application before using this route",
      },
    });
    return;
  }

  request.appUserId = userId.trim();
});

/**
 * Abort ChatVector work if the downstream HTTP peer disappears. A normal
 * completed response cleans up the listeners without aborting the operation.
 */
function downstreamSignal(
  request: FastifyRequest,
  reply: FastifyReply,
): AbortSignal {
  const controller = new AbortController();

  const abort = () => controller.abort();
  const abortIfResponseIncomplete = () => {
    if (!reply.raw.writableFinished) abort();
  };
  const cleanup = () => {
    request.raw.off("aborted", abort);
    reply.raw.off("close", abortIfResponseIncomplete);
    reply.raw.off("finish", cleanup);
  };

  request.raw.once("aborted", abort);
  reply.raw.once("close", abortIfResponseIncomplete);
  reply.raw.once("finish", cleanup);

  if (request.raw.aborted) abort();
  return controller.signal;
}

server.post("/api/documents", async (request, reply) => {
  const signal = downstreamSignal(request, reply);
  const file = await request.file();

  if (!file) {
    return reply.code(400).send({
      error: { code: "file_required", message: "Multipart field 'file' is required" },
    });
  }

  const data = await file.toBuffer();
  const uploaded = await chatVector.uploadDocument(
    {
      data,
      fileName: file.filename,
      contentType: file.mimetype,
    },
    { signal },
  );
  const ready = await chatVector.waitForReady(uploaded.documentId, {
    signal,
    timeoutMs: 60_000,
    pollIntervalMs: 2_000,
  });

  return reply.code(201).send({
    document: {
      id: uploaded.documentId,
      status: ready.status,
      createdAt: ready.createdAt,
      updatedAt: ready.updatedAt,
    },
  });
});

server.get<{ Params: { id: string } }>(
  "/api/documents/:id",
  async (request, reply) => {
    const signal = downstreamSignal(request, reply);
    const document = await chatVector.getDocumentStatus(request.params.id, {
      signal,
    });

    return {
      document: {
        id: document.documentId,
        status: document.status,
        chunks: document.chunks,
        createdAt: document.createdAt,
        updatedAt: document.updatedAt,
        queuePosition: document.queuePosition,
      },
    };
  },
);

type ChatBody = {
  question?: string;
  docId?: string;
  sessionId?: string;
  matchCount?: number;
  scope?: "session" | "tenant";
};

server.post<{ Body: ChatBody }>("/api/chat", async (request, reply) => {
  const signal = downstreamSignal(request, reply);
  const { question, docId, matchCount, scope } = request.body ?? {};

  if (typeof question !== "string" || question.trim() === "") {
    return reply.code(400).send({
      error: { code: "question_required", message: "question is required" },
    });
  }
  if (typeof docId !== "string" || docId.trim() === "") {
    return reply.code(400).send({
      error: { code: "document_required", message: "docId is required" },
    });
  }

  let sessionId = request.body.sessionId?.trim();
  if (!sessionId) {
    const session = await chatVector.createSession(undefined, { signal });
    sessionId = session.id;
  }

  const chatRequest: ChatRequest = {
    question: question.trim(),
    docId: docId.trim(),
    sessionId,
  };
  if (matchCount !== undefined) chatRequest.matchCount = matchCount;
  if (scope !== undefined) chatRequest.scope = scope;

  const response = await chatVector.chat(chatRequest, { signal });
  return { sessionId, response };
});

function isClientHttpError(
  error: unknown,
): error is Error & { statusCode: number; code?: string } {
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as { statusCode?: unknown; code?: unknown };
  return (
    typeof candidate.statusCode === "number" &&
    candidate.statusCode >= 400 &&
    candidate.statusCode < 500 &&
    (candidate.code === undefined || typeof candidate.code === "string")
  );
}

server.setErrorHandler((error, request, reply) => {
  if (error instanceof ChatVectorRateLimitError) {
    if (error.retryAfterMs !== undefined) {
      reply.header("Retry-After", Math.ceil(error.retryAfterMs / 1_000));
    }
    return reply.code(429).send({
      error: {
        code: error.code ?? "chatvector_rate_limited",
        message: "The document service is rate limited; try again later",
        retryAfterMs: error.retryAfterMs,
      },
    });
  }

  if (error instanceof ChatVectorAPIError) {
    // Upstream credentials and decoded error details stay server-side.
    const statusCode =
      error instanceof ChatVectorTimeoutError
        ? 504
        : error.kind === "auth"
          ? 502
          : error.statusCode && error.statusCode >= 400 && error.statusCode < 600
            ? error.statusCode
            : 502;

    request.log.warn(
      { kind: error.kind, code: error.code, statusCode: error.statusCode },
      "ChatVector request failed",
    );
    return reply.code(statusCode).send({
      error: {
        code: error.code ?? "chatvector_error",
        message:
          error instanceof ChatVectorTimeoutError
            ? "The document service timed out"
            : "The document service request failed",
      },
    });
  }

  if (error instanceof Error && error.name === "AbortError") {
    if (!reply.raw.destroyed) {
      return reply.code(499).send({
        error: { code: "request_cancelled", message: "Request cancelled" },
      });
    }
    return;
  }

  if (isClientHttpError(error)) {
    request.log.info(
      { code: error.code, statusCode: error.statusCode },
      "Invalid application request",
    );
    return reply.code(error.statusCode).send({
      error: {
        code: error.code ?? "invalid_request",
        message: "Invalid request",
      },
    });
  }

  request.log.error(error);
  return reply.code(500).send({
    error: { code: "internal_error", message: "Internal server error" },
  });
});

const port = Number.parseInt(process.env.PORT ?? "3000", 10);
if (!Number.isInteger(port) || port <= 0 || port > 65_535) {
  throw new Error("PORT must be an integer between 1 and 65535");
}

await server.listen({ host: "0.0.0.0", port });

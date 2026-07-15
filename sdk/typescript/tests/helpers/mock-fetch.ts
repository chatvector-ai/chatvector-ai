import { vi } from "vitest";

export type FetchInput = string | URL | Request;

export type FetchHandler = (
  input: FetchInput,
  init?: RequestInit,
) => Response | Promise<Response>;

export type FetchStep = Response | Error | FetchHandler;

/** A strict response queue: an unexpected extra request fails the test. */
export function createFetchMock(...steps: FetchStep[]) {
  let stepIndex = 0;
  return vi.fn(
    async (input: FetchInput, init?: RequestInit): Promise<Response> => {
      const step = steps[stepIndex];
      stepIndex += 1;
      if (step === undefined) {
        throw new Error(`Unexpected fetch call #${stepIndex}: ${String(input)}`);
      }
      if (step instanceof Error) {
        throw step;
      }
      if (typeof step === "function") {
        return await step(input, init);
      }
      return step;
    },
  );
}

export type FetchMock = ReturnType<typeof createFetchMock>;

export function jsonResponse(
  body: unknown,
  init: ResponseInit = {},
): Response {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return new Response(JSON.stringify(body), { ...init, headers });
}

export function textResponse(
  body: string,
  init: ResponseInit = {},
): Response {
  return new Response(body, init);
}

export function emptyResponse(status = 204): Response {
  return new Response(null, { status });
}

export function getFetchCall(mock: FetchMock, index = 0): {
  url: string;
  init: RequestInit;
} {
  const call = mock.mock.calls[index];
  if (call === undefined) {
    throw new Error(`Missing fetch call #${index + 1}`);
  }
  const input = call[0];
  const init = call[1] ?? {};
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  return { url, init };
}

export function getJsonBody(init: RequestInit): unknown {
  if (typeof init.body !== "string") {
    throw new Error("Expected a JSON string request body");
  }
  return JSON.parse(init.body) as unknown;
}

export async function getMultipartFile(init: RequestInit): Promise<{
  form: FormData;
  file: File;
  bytes: Uint8Array;
}> {
  if (!(init.body instanceof FormData)) {
    throw new Error("Expected a FormData request body");
  }
  const value = init.body.get("file");
  if (!(value instanceof Blob) || typeof (value as File).name !== "string") {
    throw new Error("Expected multipart field 'file' to contain a File");
  }
  return {
    form: init.body,
    file: value as File,
    bytes: new Uint8Array(await value.arrayBuffer()),
  };
}

/** A fetch step that remains pending until the SDK-provided signal aborts. */
export const pendingUntilAborted: FetchHandler = (_input, init) =>
  new Promise<Response>((_resolve, reject) => {
    const signal = init?.signal;
    if (signal === null || signal === undefined) {
      reject(new Error("Expected an AbortSignal"));
      return;
    }
    const rejectWithReason = (): void => {
      reject(
        "reason" in signal
          ? signal.reason
          : new DOMException("The operation was aborted", "AbortError"),
      );
    };
    if (signal.aborted) {
      rejectWithReason();
      return;
    }
    signal.addEventListener("abort", rejectWithReason, { once: true });
  });

/** A successful response whose body stays open until the request signal aborts. */
export const responseBodyPendingUntilAborted: FetchHandler = (_input, init) => {
  const signal = init?.signal;
  if (signal === null || signal === undefined) {
    throw new Error("Expected an AbortSignal");
  }
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const fail = (): void => {
        controller.error(
          "reason" in signal
            ? signal.reason
            : new DOMException("The operation was aborted", "AbortError"),
        );
      };
      if (signal.aborted) {
        fail();
      } else {
        signal.addEventListener("abort", fail, { once: true });
      }
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

export async function flushAsyncWork(rounds = 6): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await Promise.resolve();
  }
}

export async function captureRejection(
  promise: Promise<unknown>,
): Promise<unknown> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("Expected promise to reject");
}

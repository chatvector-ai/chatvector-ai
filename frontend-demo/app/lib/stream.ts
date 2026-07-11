import type { ChatSource } from "./api";

// ---------------------------------------------------------------------------
// Stream event types
// ---------------------------------------------------------------------------

export type TokenEvent = { type: "token"; text: string };
export type CompleteEvent = {
  type: "complete";
  sources: ChatSource[];
  latency_ms: number;
  model: string;
  session_id?: string;
};
export type DoneEvent = { type: "done" };
export type ErrorEvent = { type: "error"; code: string; message: string };

export type StreamEvent = TokenEvent | CompleteEvent | DoneEvent | ErrorEvent;

// ---------------------------------------------------------------------------
// SSE parser — converts a raw ReadableStream<Uint8Array> into StreamEvents
// ---------------------------------------------------------------------------

/**
 * Parse a `ReadableStream<Uint8Array>` (from a `fetch` response body) as
 * Server-Sent Events and yield typed `StreamEvent` objects.
 *
 * The parser uses a buffer to handle network chunk boundaries — a single SSE
 * event may be split across multiple `Uint8Array` chunks.  Events are
 * delimited by a blank line (`\n\n`).
 *
 * Unknown event types are silently ignored for forward compatibility.
 *
 * @param stream  The response body from `fetch()`.
 * @param signal  Optional `AbortSignal` to cancel reading.
 */
export async function* parseSSEStream(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) break;

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE events are delimited by double newlines.
      // Process all complete events currently sitting in the buffer.
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        const parsed = parseRawEvent(rawEvent);
        if (parsed) yield parsed;
      }
    }

    // Flush any remaining data in the buffer (e.g. server closed the stream
    // without a trailing blank line).
    if (buffer.trim().length > 0) {
      const parsed = parseRawEvent(buffer);
      if (parsed) yield parsed;
    }
  } finally {
    reader.releaseLock();
  }
}

// ---------------------------------------------------------------------------
// Internal: parse a single raw SSE text block into a StreamEvent
// ---------------------------------------------------------------------------

/**
 * Parse one raw SSE text block (everything between double-newline delimiters)
 * into a `StreamEvent`.
 *
 * An SSE block consists of `field: value` lines.  We care about:
 *   - `event: <type>`
 *   - `data: <payload>`   (may span multiple `data:` lines — concatenated)
 *
 * Returns `null` for unknown event types or unparsable data.
 */
export function parseRawEvent(raw: string): StreamEvent | null {
  let eventType = "";
  const dataLines: string[] = [];

  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      eventType = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
    // Lines starting with ":" are SSE comments; other prefixes are ignored.
  }

  // Combine multi-line data fields (SSE spec: join with newline).
  const data = dataLines.join("\n");

  switch (eventType) {
    case "token":
      return parseTokenEvent(data);
    case "complete":
      return parseCompleteEvent(data);
    case "done":
      return { type: "done" };
    case "error":
      return parseErrorEvent(data);
    default:
      // Unknown event type — silently ignore for forward compatibility.
      return null;
  }
}

// ---------------------------------------------------------------------------
// Per-event-type parsers
// ---------------------------------------------------------------------------

function parseTokenEvent(data: string): TokenEvent | null {
  try {
    // The backend JSON-encodes the string, so we get e.g. `"hello"`.
    const text = JSON.parse(data) as string;
    if (typeof text !== "string") return null;
    return { type: "token", text };
  } catch {
    // If the data is not valid JSON, treat it as raw text (defensive).
    return data.length > 0 ? { type: "token", text: data } : null;
  }
}

function parseCompleteEvent(data: string): CompleteEvent | null {
  try {
    const payload = JSON.parse(data) as Record<string, unknown>;
    return {
      type: "complete",
      sources: (payload.sources ?? []) as ChatSource[],
      latency_ms: (payload.latency_ms ?? 0) as number,
      model: (payload.model ?? "") as string,
      ...(typeof payload.session_id === "string"
        ? { session_id: payload.session_id }
        : {}),
    };
  } catch {
    return null;
  }
}

function parseErrorEvent(data: string): ErrorEvent | null {
  try {
    const payload = JSON.parse(data) as Record<string, unknown>;
    return {
      type: "error",
      code: String(payload.code ?? "unknown"),
      message: String(payload.message ?? "An unknown error occurred."),
    };
  } catch {
    return null;
  }
}

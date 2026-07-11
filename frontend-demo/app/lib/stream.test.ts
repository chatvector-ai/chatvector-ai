import { describe, it, expect } from "vitest";
import { parseSSEStream, parseRawEvent, type StreamEvent } from "./stream";

// ---------------------------------------------------------------------------
// Helper: create a ReadableStream from an array of string chunks
// ---------------------------------------------------------------------------
function createMockStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]));
        index++;
      } else {
        controller.close();
      }
    },
  });
}

/** Collect all events from an async generator into an array. */
async function collectEvents(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of parseSSEStream(stream, signal)) {
    events.push(event);
  }
  return events;
}

// ---------------------------------------------------------------------------
// parseRawEvent — unit tests for individual event parsing
// ---------------------------------------------------------------------------

describe("parseRawEvent", () => {
  it("parses a token event", () => {
    const result = parseRawEvent('event: token\ndata: "Hello"');
    expect(result).toEqual({ type: "token", text: "Hello" });
  });

  it("parses a complete event", () => {
    const data = JSON.stringify({
      type: "complete",
      session_id: "sess-1",
      sources: [{ file_name: "doc.pdf", page_number: 1, chunk_index: 0, score: 0.9 }],
      latency_ms: 1200,
      model: "gemini-2.5-flash",
    });
    const result = parseRawEvent(`event: complete\ndata: ${data}`);
    expect(result).toEqual({
      type: "complete",
      session_id: "sess-1",
      sources: [{ file_name: "doc.pdf", page_number: 1, chunk_index: 0, score: 0.9 }],
      latency_ms: 1200,
      model: "gemini-2.5-flash",
    });
  });

  it("parses a done event", () => {
    const result = parseRawEvent("event: done\ndata: [DONE]");
    expect(result).toEqual({ type: "done" });
  });

  it("parses an error event", () => {
    const data = JSON.stringify({
      type: "error",
      code: "llm_rate_limited",
      message: "Rate limited.",
    });
    const result = parseRawEvent(`event: error\ndata: ${data}`);
    expect(result).toEqual({
      type: "error",
      code: "llm_rate_limited",
      message: "Rate limited.",
    });
  });

  it("returns null for unknown event types", () => {
    const result = parseRawEvent("event: heartbeat\ndata: {}");
    expect(result).toBeNull();
  });

  it("returns null for events with no event type", () => {
    const result = parseRawEvent("data: something");
    expect(result).toBeNull();
  });

  it("handles multi-line data fields", () => {
    const part1 = '{"type":"complete","session_id":"s1",';
    const part2 = '"sources":[],"latency_ms":100,"model":"m"}';
    const raw = `event: complete\ndata: ${part1}\ndata: ${part2}`;
    const result = parseRawEvent(raw);
    // multi-line data is joined with \n, so we get valid JSON only if split correctly.
    // For the complete event, the JSON should parse as a single object.
    expect(result).toEqual({
      type: "complete",
      session_id: "s1",
      sources: [],
      latency_ms: 100,
      model: "m",
    });
  });

  it("parses token event with non-JSON data defensively", () => {
    const result = parseRawEvent("event: token\ndata: raw text");
    expect(result).toEqual({ type: "token", text: "raw text" });
  });

  it("handles complete event missing optional session_id", () => {
    const data = JSON.stringify({
      type: "complete",
      sources: [],
      latency_ms: 500,
      model: "test-model",
    });
    const result = parseRawEvent(`event: complete\ndata: ${data}`);
    expect(result).toEqual({
      type: "complete",
      sources: [],
      latency_ms: 500,
      model: "test-model",
    });
    // session_id should NOT be present in the result
    expect(result).not.toHaveProperty("session_id");
  });
});

// ---------------------------------------------------------------------------
// parseSSEStream — integration tests with ReadableStream
// ---------------------------------------------------------------------------

describe("parseSSEStream", () => {
  it("parses a complete stream: token → complete → done", async () => {
    const raw = [
      'event: token\ndata: "Hello"\n\n',
      'event: token\ndata: " world"\n\n',
      'event: complete\ndata: {"type":"complete","sources":[],"latency_ms":200,"model":"m"}\n\n',
      "event: done\ndata: [DONE]\n\n",
    ].join("");

    const events = await collectEvents(createMockStream([raw]));

    expect(events).toEqual([
      { type: "token", text: "Hello" },
      { type: "token", text: " world" },
      { type: "complete", sources: [], latency_ms: 200, model: "m" },
      { type: "done" },
    ]);
  });

  it("handles events split across multiple chunks", async () => {
    // Split an event right in the middle of the "data:" line
    const chunk1 = 'event: token\ndata: "Hel';
    const chunk2 = 'lo"\n\nevent: done\ndata: [DONE]\n\n';

    const events = await collectEvents(createMockStream([chunk1, chunk2]));

    expect(events).toEqual([
      { type: "token", text: "Hello" },
      { type: "done" },
    ]);
  });

  it("handles event/data split across three chunks", async () => {
    const chunk1 = "event:";
    const chunk2 = ' token\ndata: "chunk"\n';
    const chunk3 = "\nevent: done\ndata: [DONE]\n\n";

    const events = await collectEvents(createMockStream([chunk1, chunk2, chunk3]));

    expect(events).toEqual([
      { type: "token", text: "chunk" },
      { type: "done" },
    ]);
  });

  it("handles a single chunk boundary splitting \\n\\n delimiter", async () => {
    const chunk1 = 'event: token\ndata: "a"\n';
    const chunk2 = '\nevent: token\ndata: "b"\n\n';

    const events = await collectEvents(createMockStream([chunk1, chunk2]));

    expect(events).toEqual([
      { type: "token", text: "a" },
      { type: "token", text: "b" },
    ]);
  });

  it("skips unknown event types in the stream", async () => {
    const raw = [
      'event: token\ndata: "hi"\n\n',
      "event: heartbeat\ndata: {}\n\n",
      "event: done\ndata: [DONE]\n\n",
    ].join("");

    const events = await collectEvents(createMockStream([raw]));

    expect(events).toEqual([
      { type: "token", text: "hi" },
      { type: "done" },
    ]);
  });

  it("parses an error event in the stream", async () => {
    const raw = [
      'event: token\ndata: "partial"\n\n',
      'event: error\ndata: {"type":"error","code":"llm_timeout_or_connection","message":"Timeout"}\n\n',
    ].join("");

    const events = await collectEvents(createMockStream([raw]));

    expect(events).toEqual([
      { type: "token", text: "partial" },
      { type: "error", code: "llm_timeout_or_connection", message: "Timeout" },
    ]);
  });

  it("handles empty stream", async () => {
    const events = await collectEvents(createMockStream([]));
    expect(events).toEqual([]);
  });

  it("handles stream with only whitespace", async () => {
    const events = await collectEvents(createMockStream(["  \n\n"]));
    expect(events).toEqual([]);
  });

  it("flushes a trailing event without final \\n\\n", async () => {
    // Some servers may close the stream without the trailing blank line.
    const raw = 'event: token\ndata: "last"';

    const events = await collectEvents(createMockStream([raw]));

    expect(events).toEqual([{ type: "token", text: "last" }]);
  });

  it("handles many rapid token events", async () => {
    const tokens = Array.from({ length: 100 }, (_, i) => `event: token\ndata: "${i}"\n\n`);
    const events = await collectEvents(createMockStream(tokens));

    expect(events).toHaveLength(100);
    expect(events[0]).toEqual({ type: "token", text: "0" });
    expect(events[99]).toEqual({ type: "token", text: "99" });
  });

  it("respects AbortSignal", async () => {
    const controller = new AbortController();
    let tokenCount = 0;

    // Create a stream that emits 10 tokens, but we abort after 3
    const chunks = Array.from({ length: 10 }, (_, i) => `event: token\ndata: "${i}"\n\n`);
    const stream = createMockStream(chunks);

    const events: StreamEvent[] = [];
    for await (const event of parseSSEStream(stream, controller.signal)) {
      events.push(event);
      tokenCount++;
      if (tokenCount >= 3) {
        controller.abort();
      }
    }

    // Should have stopped after 3 tokens
    expect(events).toHaveLength(3);
  });
});

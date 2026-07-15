import { describe, expect, it } from "vitest";

import {
  ChatVectorAPIError,
  ChatVectorAuthError,
  ChatVectorRateLimitError,
  ChatVectorTimeoutError,
  isChatVectorError,
} from "../../src/index.js";

describe("SDK error hierarchy", () => {
  it("retains structured API error metadata", () => {
    const cause = new Error("socket closed");
    const details = { detail: { code: "bad_request" } };
    const error = new ChatVectorAPIError("Request failed", {
      statusCode: 400,
      code: "bad_request",
      details,
      cause,
    });

    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("ChatVectorAPIError");
    expect(error.kind).toBe("api");
    expect(error.message).toBe("Request failed");
    expect(error.statusCode).toBe(400);
    expect(error.code).toBe("bad_request");
    expect(error.details).toBe(details);
    expect(error.cause).toBe(cause);
  });

  it.each([
    [new ChatVectorAuthError("auth"), "ChatVectorAuthError", "auth"],
    [
      new ChatVectorRateLimitError("slow down", { retryAfterMs: 2_000 }),
      "ChatVectorRateLimitError",
      "rate_limit",
    ],
    [new ChatVectorTimeoutError("timeout"), "ChatVectorTimeoutError", "timeout"],
  ] as const)("sets %s name and stable kind", (error, name, kind) => {
    expect(error).toBeInstanceOf(ChatVectorAPIError);
    expect(error.name).toBe(name);
    expect(error.kind).toBe(kind);
  });

  it("exposes retryAfterMs only when supplied", () => {
    expect(new ChatVectorRateLimitError("limited").retryAfterMs).toBeUndefined();
    expect(
      new ChatVectorRateLimitError("limited", { retryAfterMs: 0 }).retryAfterMs,
    ).toBe(0);
  });
});

describe("isChatVectorError", () => {
  it("recognizes every concrete SDK error", () => {
    expect(isChatVectorError(new ChatVectorAPIError("api"))).toBe(true);
    expect(isChatVectorError(new ChatVectorAuthError("auth"))).toBe(true);
    expect(isChatVectorError(new ChatVectorRateLimitError("rate"))).toBe(true);
    expect(isChatVectorError(new ChatVectorTimeoutError("timeout"))).toBe(true);
  });

  it("recognizes a structurally compatible error from another package instance", () => {
    expect(isChatVectorError({ kind: "rate_limit", message: "limited" })).toBe(
      true,
    );
    const callable = Object.assign(() => undefined, {
      kind: "timeout",
      message: "timed out",
    });
    expect(isChatVectorError(callable)).toBe(true);
  });

  it.each([
    null,
    undefined,
    "error",
    1,
    {},
    { kind: "other", message: "x" },
    { kind: "api", message: 3 },
  ])("rejects non-SDK value %#", (value) => {
    expect(isChatVectorError(value)).toBe(false);
  });

  it("does not let hostile getters escape the type guard", () => {
    const value = Object.defineProperty({}, "kind", {
      get() {
        throw new Error("getter failed");
      },
    });
    expect(isChatVectorError(value)).toBe(false);
  });
});

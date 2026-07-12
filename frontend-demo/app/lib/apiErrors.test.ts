import { describe, it, expect } from "vitest";
import {
  BackendApiError,
  formatBackendErrorMessage,
  formatFieldLocation,
  parseBackendErrorBody,
  parseBackendErrorDetail,
} from "./apiErrors";

describe("parseBackendErrorDetail", () => {
  it("parses structured detail with code and message", () => {
    expect(
      parseBackendErrorDetail({
        code: "rate_limited",
        message: "Too many requests. Please slow down.",
      })
    ).toEqual({
      code: "rate_limited",
      message: "Too many requests. Please slow down.",
    });
  });

  it("parses validation detail with fields", () => {
    expect(
      parseBackendErrorDetail({
        code: "validation_error",
        message: "Request validation failed",
        fields: [
          {
            loc: ["body", "question"],
            msg: "ensure this value has at most 2000 characters",
          },
        ],
      })
    ).toEqual({
      code: "validation_error",
      message: "Request validation failed",
      fields: [
        {
          loc: ["body", "question"],
          msg: "ensure this value has at most 2000 characters",
        },
      ],
    });
  });

  it("parses string detail values", () => {
    expect(parseBackendErrorDetail("Session not found")).toEqual({
      message: "Session not found",
    });
  });

  it("falls back for malformed detail objects", () => {
    expect(parseBackendErrorDetail({ code: "validation_error" })).toEqual({
      message: "An unexpected error occurred.",
    });
    expect(parseBackendErrorDetail(null)).toEqual({
      message: "An unexpected error occurred.",
    });
  });
});

describe("parseBackendErrorBody", () => {
  it("extracts detail from a response body envelope", () => {
    expect(
      parseBackendErrorBody({
        detail: {
          code: "document_not_found",
          message: "Document not found.",
        },
      })
    ).toEqual({
      code: "document_not_found",
      message: "Document not found.",
    });
  });

  it("falls back when the body has no detail", () => {
    expect(parseBackendErrorBody({ error: "nope" })).toEqual({
      message: "An unexpected error occurred.",
    });
  });
});

describe("formatBackendErrorMessage", () => {
  it("formats validation field hints on separate lines", () => {
    expect(
      formatBackendErrorMessage({
        code: "validation_error",
        message: "Request validation failed",
        fields: [
          {
            loc: ["body", "question"],
            msg: "ensure this value has at most 2000 characters",
          },
          {
            loc: ["body", "match_count"],
            msg: "ensure this value is greater than or equal to 1",
          },
        ],
      })
    ).toBe(
      "Request validation failed\nquestion: ensure this value has at most 2000 characters\nmatch_count: ensure this value is greater than or equal to 1"
    );
  });

  it("returns the message alone when no fields are present", () => {
    expect(
      formatBackendErrorMessage({
        code: "invalid_batch_request",
        message: "Batch request is invalid.",
      })
    ).toBe("Batch request is invalid.");
  });
});

describe("formatFieldLocation", () => {
  it("drops the body prefix from FastAPI locations", () => {
    expect(formatFieldLocation(["body", "question"])).toBe("question");
    expect(formatFieldLocation(["body", "queries", 0, "doc_ids"])).toBe(
      "queries.0.doc_ids"
    );
  });
});

describe("BackendApiError", () => {
  it("carries parsed detail and http status", () => {
    const parsed = {
      code: "rate_limited",
      message: "Too many requests. Please slow down.",
    };
    const err = new BackendApiError(
      formatBackendErrorMessage(parsed),
      parsed,
      429
    );

    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("Too many requests. Please slow down.");
    expect(err.parsed.code).toBe("rate_limited");
    expect(err.httpStatus).toBe(429);
  });
});

describe("isGenericBackendError", () => {
  it("detects empty parsed errors", async () => {
    const { isGenericBackendError } = await import("./apiErrors");
    expect(
      isGenericBackendError({ message: "An unexpected error occurred." })
    ).toBe(true);
    expect(
      isGenericBackendError({
        code: "validation_error",
        message: "Request validation failed",
      })
    ).toBe(false);
  });
});

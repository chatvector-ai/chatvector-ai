import { describe, expect, it } from "vitest";
import {
  buildBatchQueryItemFields,
  buildConfigurationCompareQueryItem,
  clearRetrievalOverride,
  createEmptyRetrievalOverrideDraft,
  setRetrievalOverride,
} from "./retrievalRequestOverrides";

describe("retrievalRequestOverrides", () => {
  it("omits untouched fields from batch query items", () => {
    const draft = createEmptyRetrievalOverrideDraft();
    expect(buildBatchQueryItemFields(draft)).toEqual({});
  });

  it("sends only explicitly set retrieval and history fields", () => {
    let draft = createEmptyRetrievalOverrideDraft();
    draft = setRetrievalOverride(draft, "hybrid_enabled", true);
    draft = setRetrievalOverride(draft, "match_count", 8);
    draft = setRetrievalOverride(draft, "history_aware_retrieval", false);

    expect(buildBatchQueryItemFields(draft)).toEqual({
      hybrid_enabled: true,
      match_count: 8,
      history: { history_aware_retrieval: false },
    });
  });

  it("clears an override when the developer removes it", () => {
    let draft = setRetrievalOverride(
      createEmptyRetrievalOverrideDraft(),
      "match_count",
      8,
    );
    draft = clearRetrievalOverride(draft, "match_count");
    expect(buildBatchQueryItemFields(draft)).toEqual({});
  });

  it("sends scope only when explicitly overridden on a config side", () => {
    const draftA = setRetrievalOverride(
      createEmptyRetrievalOverrideDraft(),
      "scope",
      "tenant",
    );
    let draftB = createEmptyRetrievalOverrideDraft();
    draftB = setRetrievalOverride(draftB, "match_count", 7);

    expect(buildConfigurationCompareQueryItem("Q?", ["d1"], draftA)).toEqual({
      question: "Q?",
      doc_ids: ["d1"],
      scope: "tenant",
    });
    expect(buildConfigurationCompareQueryItem("Q?", ["d1"], draftB)).toEqual({
      question: "Q?",
      doc_ids: ["d1"],
      match_count: 7,
    });
  });

  it("builds two query items that share question and documents", () => {
    const question = "What is the policy?";
    const docIds = ["doc-1", "doc-2"];
    const configA = setRetrievalOverride(
      createEmptyRetrievalOverrideDraft(),
      "hybrid_enabled",
      true,
    );
    const configB = setRetrievalOverride(
      createEmptyRetrievalOverrideDraft(),
      "match_count",
      10,
    );

    expect(buildConfigurationCompareQueryItem(question, docIds, configA)).toEqual({
      question,
      doc_ids: docIds,
      hybrid_enabled: true,
    });
    expect(buildConfigurationCompareQueryItem(question, docIds, configB)).toEqual({
      question,
      doc_ids: docIds,
      match_count: 10,
    });
  });
});

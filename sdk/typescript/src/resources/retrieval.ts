import type { RequestOptions, RetrievalPresetDiscoveryResponse } from "../models.js";
import { HttpClient } from "../internal/http.js";
import { isRecord, signalOption, stringValue } from "../internal/utils.js";

export class RetrievalResource {
  constructor(private readonly http: HttpClient) {}

  async listRetrievalPresets(
    options: RequestOptions = {},
  ): Promise<RetrievalPresetDiscoveryResponse> {
    const payload = await this.http.requestJson("GET", "/retrieval/presets", {
      ...signalOption(options.signal),
    });
    return mapRetrievalPresetDiscovery(payload);
  }
}

function mapRetrievalPresetDiscovery(
  payload: unknown,
): RetrievalPresetDiscoveryResponse {
  const record = isRecord(payload) ? payload : {};
  const names = record.preset_names;
  const providers = record.reranker_providers;
  return {
    presetNames: Array.isArray(names)
      ? names.map((name) => stringValue(name)).filter((name): name is string => name !== undefined)
      : [],
    rerankerProviders: Array.isArray(providers)
      ? providers
          .map((provider) => stringValue(provider))
          .filter((provider): provider is string => provider !== undefined)
      : [],
    _raw: record,
  };
}

"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type AdvancedRetrievalExplicitFields,
  type AdvancedRetrievalState,
  loadAdvancedRetrievalState,
  saveAdvancedRetrievalState,
} from "../advancedRetrieval";
import { clampMatchCount, type RetrievalScope } from "../retrievalSettings";
import type {
  QueryTransformationStrategy,
  RerankerProvider,
} from "../advancedRetrieval";
import type { DocumentScalarMetadata } from "../documentMetadata";

export function useAdvancedRetrieval() {
  const [state, setState] = useState<AdvancedRetrievalState>({
    explicit: {},
  });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setState(loadAdvancedRetrievalState());
    setLoaded(true);
  }, []);

  const patchExplicit = useCallback(
    (patch: Partial<AdvancedRetrievalExplicitFields>) => {
      setState((prev) => {
        const next: AdvancedRetrievalState = {
          explicit: { ...prev.explicit, ...patch },
        };
        saveAdvancedRetrievalState(next);
        return next;
      });
    },
    []
  );

  const setScope = useCallback(
    (scope: RetrievalScope) => patchExplicit({ scope }),
    [patchExplicit]
  );

  const setMatchCount = useCallback(
    (matchCount: number) =>
      patchExplicit({ matchCount: clampMatchCount(matchCount) }),
    [patchExplicit]
  );

  const setHybridEnabled = useCallback(
    (hybridEnabled: boolean) => patchExplicit({ hybridEnabled }),
    [patchExplicit]
  );

  const setRerankingEnabled = useCallback(
    (rerankingEnabled: boolean) => patchExplicit({ rerankingEnabled }),
    [patchExplicit]
  );

  const setRerankerProvider = useCallback(
    (rerankerProvider: RerankerProvider) => patchExplicit({ rerankerProvider }),
    [patchExplicit]
  );

  const setQueryTransformationEnabled = useCallback(
    (queryTransformationEnabled: boolean) =>
      patchExplicit({ queryTransformationEnabled }),
    [patchExplicit]
  );

  const setQueryTransformationStrategy = useCallback(
    (queryTransformationStrategy: QueryTransformationStrategy) =>
      patchExplicit({ queryTransformationStrategy }),
    [patchExplicit]
  );

  const setHistoryAwareRetrieval = useCallback(
    (historyAwareRetrieval: boolean) => patchExplicit({ historyAwareRetrieval }),
    [patchExplicit]
  );

  const setRetrievalHistoryWindow = useCallback(
    (retrievalHistoryWindow: number) =>
      patchExplicit({ retrievalHistoryWindow: Math.round(retrievalHistoryWindow) }),
    [patchExplicit]
  );

  const setGenerationHistoryWindow = useCallback(
    (generationHistoryWindow: number) =>
      patchExplicit({
        generationHistoryWindow: Math.round(generationHistoryWindow),
      }),
    [patchExplicit]
  );

  const setMetadataFilter = useCallback(
    (metadataFilter: DocumentScalarMetadata | undefined) => {
      setState((prev) => {
        const explicit = { ...prev.explicit };
        if (
          metadataFilter === undefined ||
          Object.keys(metadataFilter).length === 0
        ) {
          delete explicit.metadataFilter;
        } else {
          explicit.metadataFilter = metadataFilter;
        }
        const next: AdvancedRetrievalState = { explicit };
        saveAdvancedRetrievalState(next);
        return next;
      });
    },
    []
  );

  const setPreset = useCallback((preset: string | undefined) => {
    setState((prev) => {
      const explicit = { ...prev.explicit };
      const trimmed = preset?.trim();
      if (!trimmed) {
        delete explicit.preset;
      } else {
        explicit.preset = trimmed;
      }
      const next: AdvancedRetrievalState = { explicit };
      saveAdvancedRetrievalState(next);
      return next;
    });
  }, []);

  return {
    state,
    loaded,
    setScope,
    setMatchCount,
    setHybridEnabled,
    setRerankingEnabled,
    setRerankerProvider,
    setQueryTransformationEnabled,
    setQueryTransformationStrategy,
    setHistoryAwareRetrieval,
    setRetrievalHistoryWindow,
    setGenerationHistoryWindow,
    setMetadataFilter,
    setPreset,
  };
}

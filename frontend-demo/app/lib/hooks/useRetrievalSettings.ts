"use client";

import { useCallback, useEffect, useState } from "react";
import {
  clampMatchCount,
  DEFAULT_RETRIEVAL_SETTINGS,
  loadRetrievalSettings,
  saveRetrievalSettings,
  type RetrievalScope,
  type RetrievalSettings,
} from "../retrievalSettings";

export function useRetrievalSettings() {
  const [settings, setSettings] = useState<RetrievalSettings>(
    DEFAULT_RETRIEVAL_SETTINGS
  );
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setSettings(loadRetrievalSettings());
    setLoaded(true);
  }, []);

  const setScope = useCallback((scope: RetrievalScope) => {
    setSettings((prev) => {
      const next = { ...prev, scope };
      saveRetrievalSettings(next);
      return next;
    });
  }, []);

  const setMatchCount = useCallback((matchCount: number) => {
    setSettings((prev) => {
      const next = { ...prev, matchCount: clampMatchCount(matchCount) };
      saveRetrievalSettings(next);
      return next;
    });
  }, []);

  return { settings, setScope, setMatchCount, loaded };
}

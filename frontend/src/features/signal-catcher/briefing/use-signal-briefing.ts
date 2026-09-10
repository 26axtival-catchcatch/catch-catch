"use client";

import { useCallback, useEffect, useState } from "react";

import type { Briefing } from "./types";
import { BriefingClient } from "./briefing-client";

const client = new BriefingClient();

export function useSignalBriefing() {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  const loadMore = useCallback(async () => {
    if (loadingMore || briefing?.nextOffset === null || briefing?.nextOffset === undefined) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const next = await client.getBriefing(undefined, briefing.nextOffset);
      setBriefing((current) => current ? {
        ...next,
        signals: [...current.signals, ...next.signals.filter((signal) => !current.signals.some((item) => item.id === signal.id))],
      } : next);
    } catch (reason) {
      setLoadMoreError(reason instanceof Error ? reason.message : "다음 브리핑을 불러오지 못했습니다.");
    } finally {
      setLoadingMore(false);
    }
  }, [briefing?.nextOffset, loadingMore]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    client.getBriefing(controller.signal)
      .then(setBriefing)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "브리핑을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);

  return { briefing, loading, loadingMore, loadMoreError, error, refresh, loadMore };
}

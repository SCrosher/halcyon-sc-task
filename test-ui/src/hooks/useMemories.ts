import { useCallback, useEffect, useRef, useState } from "react";
import { type AgentApi, type ApiError, asApiError, isAbort } from "../lib/api";
import type { Memory } from "../lib/types";

export interface MemoriesState {
  items: Memory[];
  loading: boolean;
  error?: ApiError;
  fetchedAt?: Date;
  /** ids that are new or changed since the previous fetch */
  fresh: Set<string>;
}

function empty(): MemoriesState {
  return { items: [], loading: false, fresh: new Set() };
}

/** The member's memories, reloaded whenever the API or member changes. */
export function useMemories(api: AgentApi, memberId: string, enabled: boolean) {
  const [memories, setMemories] = useState<MemoriesState>(empty);
  const memoriesRef = useRef(memories);
  memoriesRef.current = memories;
  const sessionRef = useRef(new AbortController());

  const refresh = useCallback(async () => {
    if (!enabled) return;
    const signal = sessionRef.current.signal;
    setMemories((m) => ({ ...m, loading: true }));
    try {
      const list = await api.getMemories(memberId, signal);
      const prev = memoriesRef.current;
      const before = new Map(prev.items.map((m) => [m.id, m.updated_at]));
      const fresh = new Set(
        prev.fetchedAt ? list.filter((m) => before.get(m.id) !== m.updated_at).map((m) => m.id) : [],
      );
      setMemories({ items: list, loading: false, fetchedAt: new Date(), fresh });
    } catch (e) {
      if (isAbort(e)) return;
      setMemories((m) => ({ ...m, loading: false, error: asApiError(e), fetchedAt: new Date() }));
    }
  }, [api, memberId, enabled]);

  useEffect(() => {
    const ctrl = new AbortController();
    sessionRef.current = ctrl;
    const cleared = empty();
    memoriesRef.current = cleared;
    setMemories(cleared);
    void refresh();
    return () => ctrl.abort();
  }, [refresh]);

  return { memories, refresh };
}

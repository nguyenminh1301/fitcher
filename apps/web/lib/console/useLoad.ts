"use client";

import { useCallback, useEffect, useState } from "react";

export type Loaded<T> = { data: T | null; failed: boolean; reload: () => Promise<void> };

/** Loads a console section's data with ``load`` (memoise it with useCallback) and reloads it after a change.
 *  Each load replaces the state object, so a page re-renders even when the api returns the same array. */
export function useLoad<T>(load: () => Promise<T>): Loaded<T> {
  const [state, setState] = useState<{ data: T | null; failed: boolean }>({ data: null, failed: false });
  const reload = useCallback(async () => {
    try {
      const data = await load();
      setState({ data, failed: false });
    } catch {
      setState((previous) => ({ data: previous.data, failed: true }));
    }
  }, [load]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { ...state, reload };
}

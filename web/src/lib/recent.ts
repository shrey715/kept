"use client";

import { useCallback } from "react";
import { useStored } from "./stored";

const NONE: string[] = [];

export function useRecentCases() {
  const [recent, setRecent] = useStored<string[]>("kept.recentCases", NONE);
  const remember = useCallback(
    (id: string) => setRecent([id, ...recent.filter((x) => x !== id)].slice(0, 8)),
    [recent, setRecent],
  );
  return { recent, remember };
}

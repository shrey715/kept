"use client";

// localStorage as a React store (useSyncExternalStore): no effects, safe on the server,
// and every component reading a key re-renders when it changes. Values are per browser.
import { useCallback, useMemo, useSyncExternalStore } from "react";

const listeners = new Set<() => void>();

function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // private mode or blocked storage: behave as empty
  }
}

/** `fallback` must be a stable (module-level) value. */
export function useStored<T>(key: string, fallback: T): [T, (v: T) => void] {
  const raw = useSyncExternalStore(subscribe, () => read(key), () => null);
  const value = useMemo(() => {
    if (raw == null) return fallback;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return fallback;
    }
  }, [raw, fallback]);
  const set = useCallback(
    (v: T) => {
      try {
        localStorage.setItem(key, JSON.stringify(v));
      } catch {}
      listeners.forEach((l) => l());
    },
    [key],
  );
  return [value, set];
}

const noop = () => () => {};
/** False during the server render and hydration, true after: gate redirects on stored state. */
export function useHydrated(): boolean {
  return useSyncExternalStore(noop, () => true, () => false);
}

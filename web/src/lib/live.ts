// A small stale-while-revalidate cache for page data. A page starts from what it last saw (peek), refreshes in
// the background, and a hover can warm a page before the click (prefetch). Concurrent loads of one key share one
// request. ponytail: in memory, per tab; a shared cache (SWR, React Query) if pages ever need cross-tab sync.

type Entry = { value?: unknown; at: number; inflight?: Promise<unknown> };
const store = new Map<string, Entry>();
const FRESH_MS = 15_000; // a prefetch younger than this is used as-is

export function peek<T>(key: string): T | undefined {
  return store.get(key)?.value as T | undefined;
}

/** The value for `key`: a fresh cached one, the request already in flight, or a new request. */
export function load<T>(key: string, fetcher: () => Promise<T>, { fresh = FRESH_MS } = {}): Promise<T> {
  const e = store.get(key);
  if (e?.inflight) return e.inflight as Promise<T>;
  if (e && e.value !== undefined && Date.now() - e.at < fresh) return Promise.resolve(e.value as T);
  const inflight = fetcher().then(
    (value) => {
      store.set(key, { value, at: Date.now() });
      return value;
    },
    (err: unknown) => {
      const prev = store.get(key);
      store.set(key, { value: prev?.value, at: prev?.at ?? 0 }); // keep the stale value, drop the failed request
      throw err;
    },
  );
  store.set(key, { value: e?.value, at: e?.at ?? 0, inflight });
  return inflight;
}

/** Warm a key (e.g. on hover); errors are ignored, the page will retry. */
export function prefetch<T>(key: string, fetcher: () => Promise<T>): void {
  load(key, fetcher).catch(() => undefined);
}

/** After a change, the next load fetches again (the stale value still shows meanwhile). */
export function invalidate(prefix: string): void {
  for (const [k, e] of store) if (k.startsWith(prefix)) store.set(k, { value: e.value, at: 0 });
}

export function set<T>(key: string, value: T): void {
  store.set(key, { value, at: Date.now() });
}

export const keys = {
  queue: (userId: string) => `queue:${userId}`,
  card: (caseId: string, userId: string) => `card:${caseId}:${userId}`,
  customer: (caseId: string, userId: string) => `customer:${caseId}:${userId}`,
  approvals: (userId: string) => `approvals:${userId}`,
  portfolio: (userId: string) => `portfolio:${userId}`,
  history: (caseId: string, userId: string) => `history:${caseId}:${userId}`,
};

"use client";

import { useEffect, useState } from "react";
import { Banner, Button, Panel, Skeleton } from "@/components/ui";
import { api, type StewardItem } from "@/lib/api";
import { useIdentity } from "@/lib/identity";

export default function StewardPage() {
  const { me } = useIdentity();
  const [items, setItems] = useState<StewardItem[] | null>(null);
  const [done, setDone] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stewardQueue().then(setItems, (e: Error) => setError(e.message));
  }, []);

  async function resolve(id: string, verdict: string) {
    try {
      const r = await api.stewardResolve(id, verdict, me.userId);
      setDone((d) => ({ ...d, [id]: r.status }));
    } catch (e) {
      setDone((d) => ({ ...d, [id]: `error: ${(e as Error).message}` }));
    }
  }

  return (
    <Panel title="Match review queue">
      {error && <Banner tone="bad">Couldn&apos;t load the queue: {error}</Banner>}
      {!error && !items && <Skeleton className="h-24" />}
      {items?.length === 0 && <p className="text-sm text-muted">Nothing to review.</p>}
      {items && items.length > 0 && (
        <ul className="divide-y divide-line">
          {items.map((i) => (
            <li key={i.item_id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="font-mono text-sm">
                  {i.left_key} <span className="text-muted">vs</span> {i.right_key}
                </p>
                <p className="text-xs text-muted">
                  score {i.score.toFixed(2)} · {i.reasons.join("; ")}
                </p>
              </div>
              {done[i.item_id] ? (
                <span className="text-sm text-muted">{done[i.item_id]}</span>
              ) : (
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={() => void resolve(i.item_id, "merge")}>
                    Same person
                  </Button>
                  <Button variant="ghost" onClick={() => void resolve(i.item_id, "split")}>
                    Different people
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { NbaCard } from "@/components/nba-card";
import { Banner, Button, Skeleton } from "@/components/ui";
import { ApiError, api, type NBACard } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { useRecentCases } from "@/lib/recent";

type Loaded = { key: string; card?: NBACard; error?: string };

export default function CasePage({ params }: { params: Promise<{ caseId: string }> }) {
  const { caseId } = use(params);
  const { me } = useIdentity();
  const { remember } = useRecentCases();
  const [nonce, setNonce] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = `${caseId}|${me.userId}|${me.role}|${nonce}`;

  useEffect(() => {
    let live = true;
    api.card(caseId, me.userId, me.role).then(
      (card) => {
        if (!live) return;
        setLoaded({ key, card });
        remember(caseId);
      },
      (e: Error) => {
        if (!live) return;
        const status = e instanceof ApiError ? e.status : 0;
        const error =
          status === 403
            ? `${caseId} isn't in your queue (${me.userId}, ${me.role.replaceAll("_", " ")}).`
            : status === 404
              ? `No open case ${caseId}.`
              : `Couldn't load the card: ${e.message}`;
        setLoaded({ key, error });
      },
    );
    return () => {
      live = false;
    };
    // remember changes whenever the recent list does; it must not refetch the card
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = loaded?.key === key ? loaded : null; // a stale result never shows for a new key
  return (
    <div className="grid gap-4">
      <div className="flex items-center gap-3 text-sm">
        <Link href="/" className="text-muted hover:text-ink">
          Cases
        </Link>
        <span className="text-muted">/</span>
        <span className="font-mono">{caseId}</span>
        <Button variant="ghost" className="ml-auto py-1" onClick={() => setNonce((n) => n + 1)}>
          Refresh
        </Button>
      </div>
      {current?.error && <Banner tone="bad">{current.error}</Banner>}
      {!current && (
        <div className="grid gap-4">
          <Skeleton className="h-32" />
          <Skeleton className="h-64" />
        </div>
      )}
      {current?.card && <NbaCard key={key} card={current.card} />}
    </div>
  );
}

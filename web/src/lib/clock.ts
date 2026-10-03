"use client";

import { useEffect, useState } from "react";
import { api, type Health } from "./api";

/** The server's clock (the demo runs on business hours), ticking locally between fetches. */
export function useServerClock(): { now: Date | null; health: Health | null } {
  const [got, setGot] = useState<{ health: Health; at: number } | null>(null);
  const [wall, setWall] = useState(() => Date.now());
  useEffect(() => {
    let live = true;
    api.health().then((h) => live && setGot({ health: h, at: Date.now() }), () => {});
    const id = setInterval(() => setWall(Date.now()), 15_000);
    return () => {
      live = false;
      clearInterval(id);
    };
  }, []);
  const now = got ? new Date(new Date(got.health.now).getTime() + Math.max(0, wall - got.at)) : null;
  return { now, health: got?.health ?? null };
}

/** ISO time for decisions: the server clock if known, else the browser's. */
export function nowIso(now: Date | null): string {
  return (now ?? new Date()).toISOString();
}

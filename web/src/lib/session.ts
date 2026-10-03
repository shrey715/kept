"use client";

// Who is using the screen. ponytail: a persona picked on /signin and kept in localStorage;
// real sign-in (SSO) replaces it, and the API trusts it only because this is a demo.
import { useEffect, useMemo, useState } from "react";
import { api, type Role } from "./api";
import { useStored } from "./stored";

export type Persona = { userId: string; role: Role; name: string; title: string; blurb: string; home: string };

export const PERSONAS: Persona[] = [
  { userId: "agent-7", role: "agent", name: "Aisha Khan", title: "Collections agent", home: "/queue",
    blurb: "Works a queue of cases. Releases Amber calls and promises on their own cases." },
  { userId: "hs-1", role: "hardship_specialist", name: "Maya Singh", title: "Hardship specialist", home: "/approvals",
    blurb: "Gives the first approval on Red cases: hardship, vulnerability, plan changes." },
  { userId: "tl-1", role: "team_lead", name: "Tom Leblanc", title: "Team lead", home: "/approvals",
    blurb: "Second person on Red cases. Samples and releases the daily Green batch." },
  { userId: "c-1", role: "compliance", name: "Elena Petrova", title: "Compliance", home: "/audit",
    blurb: "Reads the full audit trail and unmasked records. Can be the second person on Red." },
  { userId: "an-1", role: "analyst", name: "Noah Kim", title: "Analyst", home: "/ask",
    blurb: "Asks questions in plain English. Sees aggregates only, never a single case." },
  { userId: "ds-1", role: "data_steward", name: "Sara Ali", title: "Data steward", home: "/steward",
    blurb: "Reviews uncertain customer matches before they merge into one golden ID." },
];

const NONE: Persona | null = null;

// The demo cases belong to "agent-7"; the real release has no such agent. On the real server Aisha works a
// real agent's queue (the one the guided demo uses), so her queue and cases aren't empty.
export const REAL_USER_IDS: Record<string, string> = { "agent-7": "AG-8365" };

let realServer: Promise<boolean> | null = null; // one /health call per page load

function useRealServer(): boolean {
  const [real, setReal] = useState(false);
  useEffect(() => {
    let live = true;
    (realServer ??= api.health().then((h) => h.demo === false, () => false)).then((r) => live && setReal(r));
    return () => {
      live = false;
    };
  }, []);
  return real;
}

export function useSession() {
  const [stored, setMe] = useStored<Persona | null>("kept.persona", NONE);
  const real = useRealServer();
  const me = useMemo(
    () => (stored && real && REAL_USER_IDS[stored.userId] ? { ...stored, userId: REAL_USER_IDS[stored.userId] } : stored),
    [stored, real],
  );
  return { me, signIn: (p: Persona) => setMe(p), signOut: () => setMe(null) };
}

export const can = {
  queue: (r: Role) => ["agent", "hardship_specialist", "team_lead", "compliance"].includes(r),
  approvals: (r: Role) => ["agent", "hardship_specialist", "team_lead", "compliance"].includes(r),
  audit: (r: Role) => ["hardship_specialist", "team_lead", "compliance"].includes(r),
  steward: (r: Role) => ["data_steward", "team_lead", "engineer"].includes(r),
};

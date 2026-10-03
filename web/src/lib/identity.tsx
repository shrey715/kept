"use client";

// Who is using the screen. ponytail: picked from a menu and kept in localStorage for the demo;
// real sign-in (SSO) replaces this, and the API trusts it only because it's a demo.
import type { Role } from "./api";
import { useStored } from "./stored";

type Identity = { userId: string; role: Role };
const DEFAULT: Identity = { userId: "agent-7", role: "agent" };

export function useIdentity() {
  const [me, setMe] = useStored<Identity>("kept.identity", DEFAULT);
  return { me, setMe };
}

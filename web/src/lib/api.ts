// Typed client for the FastAPI service. Types are generated from its OpenAPI schema
// (`pnpm api:types`), so they follow src/kept/contracts.
import type { components } from "./api-schema";

type S = components["schemas"];
export type NBACard = S["NBACard"];
export type Proposal = S["Proposal"];
export type ReleaseDecision = S["ReleaseDecision"];
export type ReleaseResult = S["ReleaseResult"];
export type AskAnswer = S["AskAnswer"];
export type Refusal = S["Refusal"];
export type Clarification = S["Clarification"];
export type AskResponse = AskAnswer | Refusal | Clarification;
export type StewardItem = S["StewardItemOut"];
export type Role = S["Role"];
export type Action = S["Action"];
export type Tier = S["ReleaseTier"];

export const ROLES: Role[] = [
  "agent",
  "hardship_specialist",
  "team_lead",
  "compliance",
  "analyst",
  "data_steward",
  "engineer",
];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const detail = body?.detail;
    const msg = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : r.statusText;
    throw new ApiError(r.status, msg);
  }
  return body as T;
}

export const api = {
  card: (caseId: string, userId: string, role: Role) =>
    call<NBACard>(`/cases/${encodeURIComponent(caseId)}/nba?${new URLSearchParams({ user_id: userId, role })}`),
  decide: (d: ReleaseDecision) =>
    call<ReleaseResult>(`/proposals/${encodeURIComponent(d.proposal_id)}/decision`, {
      method: "POST",
      body: JSON.stringify(d),
    }),
  ask: (question: string, userId: string, role: Role) =>
    call<AskResponse>("/ask", { method: "POST", body: JSON.stringify({ question, user_id: userId, role }) }),
  stewardQueue: () => call<StewardItem[]>("/steward/queue"),
  stewardResolve: (itemId: string, verdict: string, stewardId: string) =>
    call<{ status: string }>(`/steward/items/${encodeURIComponent(itemId)}`, {
      method: "POST",
      body: JSON.stringify({ verdict, steward_id: stewardId }),
    }),
};

// ---------------------------------------------------------------- formatting
export const ACTION_LABEL: Record<Action, string> = {
  wait: "Wait",
  email: "Reminder email",
  push: "App reminder",
  sms_payment_link: "SMS payment link",
  call: "Call",
  promise_request: "Ask for a promise",
  payment_plan: "Offer a payment plan",
  hardship_review: "Hardship review",
};

export const money = (v: string | number) =>
  Number(v).toLocaleString("en-CA", { style: "currency", currency: "CAD" }).replace(/\.00$/, "");

export const pct = (p: number) => `${Math.round(p * 100)}%`;

export const when = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString("en-CA", { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "";

export const humanize = (s: string) => s.replaceAll("_", " ");

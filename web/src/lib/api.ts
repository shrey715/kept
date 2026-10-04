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
export type Citation = S["Citation"];
export type SourceText = S["SourceText"];
export type BenchOut = S["BenchOut"];
export type BenchSuite = S["BenchSuite"];
export type StewardItem = S["StewardItemOut"];
export type QueueItem = S["QueueItem"];
export type ApprovalItem = S["ApprovalItem"];
export type AuditEvent = S["AuditEvent"];
export type Customer = S["GoldenCustomer"];
export type Health = S["HealthResponse"];
export type Role = S["Role"];
export type Action = S["Action"];
export type Tier = S["ReleaseTier"];
export type AuditKind = S["AuditKind"];
export type TextExtraction = S["TextExtraction"];
export type ChartChoice = S["ChartChoice"];
export type PayOffer = S["PayOffer"];
export type PromiseSizing = S["PromiseSizing"];
export type ChartOption = S["ChartOption"];
/** Demo-only route shape (kept.app.demo): a note and what was read from it. */
export type NoteExtraction = { note: string; extraction: TextExtraction };

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
    const msg =
      typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : r.status >= 500 ? "Service error" : r.statusText;
    throw new ApiError(r.status, msg);
  }
  return body as T;
}

type Who = { userId: string; role: Role };
const q = (w: Who, extra: Record<string, string> = {}) =>
  new URLSearchParams({ user_id: w.userId, role: w.role, ...extra }).toString();
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => call<Health>("/health"),
  queue: (w: Who) => call<QueueItem[]>(`/queue?${q(w)}`),
  card: (caseId: string, w: Who) => call<NBACard>(`/cases/${encodeURIComponent(caseId)}/nba?${q(w)}`),
  customer: (caseId: string, w: Who) => call<Customer>(`/cases/${encodeURIComponent(caseId)}/customer?${q(w)}`),
  approvals: (w: Who) => call<ApprovalItem[]>(`/approvals?${q(w)}`),
  audit: (w: Who, opts: { caseId?: string; kind?: AuditKind } = {}) =>
    call<AuditEvent[]>(
      `/audit?${q(w, { ...(opts.caseId ? { case_id: opts.caseId } : {}), ...(opts.kind ? { kind: opts.kind } : {}) })}`,
    ),
  decide: (d: ReleaseDecision) =>
    call<ReleaseResult>(`/proposals/${encodeURIComponent(d.proposal_id)}/decision`, post(d)),
  /** Add a note: live extraction (C), then the re-checked card. */
  note: (caseId: string, text: string, w: Who) =>
    call<NBACard>(`/cases/${encodeURIComponent(caseId)}/notes`, post({ text, user_id: w.userId, role: w.role })),
  /** A case's notes and their extractions, newest first: the demo world, or C's store. */
  extractions: (caseId: string, w: Who, demo: boolean) =>
    call<NoteExtraction[]>(`${demo ? "/demo" : ""}/cases/${encodeURIComponent(caseId)}/extractions?${q(w)}`),
  /** Confirm or edit at wrap-up. Demo route in demo mode, C's /extractions route otherwise. */
  confirmExtraction: (sourceId: string, agentId: string, edits: Record<string, unknown>, demo: boolean) =>
    call<TextExtraction>(
      `${demo ? "/demo" : ""}/extractions/${encodeURIComponent(sourceId)}/confirm`,
      post({ agent_id: agentId, edits }),
    ),
  ask: (question: string, w: Who) => call<AskResponse>("/ask", post({ question, user_id: w.userId, role: w.role })),
  benchSuites: () => call<BenchSuite[]>("/bench/suites"),
  benchQuestion: (question: Record<string, string>, gold?: Record<string, string>) =>
    call<BenchOut>("/bench/question", post({ question, gold: gold ?? null })),
  /** A chart for rows the Ask already returned (the LLM or the rules pick); shown in the Ask page's Chart tab. */
  chart: (a: { question: string; sql: string | null; columns: string[]; rows: unknown[][] }, w: Who) =>
    call<ChartChoice>("/chart", post({ ...a, user_id: w.userId, role: w.role })),
  /** #89: the customer's SMS link. No sign-in; only a released SMS proposal has one. */
  payOffer: (token: string) => call<PayOffer>(`/pay/${encodeURIComponent(token)}`),
  payChoose: (token: string, installments: number) =>
    call<PromiseSizing>(`/pay/${encodeURIComponent(token)}`, post({ installments })),
  askSource: (citation: Citation, w: Who) => call<SourceText>("/ask/source", post({ citation, user_id: w.userId, role: w.role })),
  stewardQueue: () => call<StewardItem[]>("/steward/queue"),
  stewardResolve: (itemId: string, verdict: string, stewardId: string) =>
    call<{ status: string }>(`/steward/items/${encodeURIComponent(itemId)}`, post({ verdict, steward_id: stewardId })),
};

/** A decision body with every optional field set, so callers only name what they change. */
export function decision(p: Proposal, w: Who, now: string, over: Partial<ReleaseDecision> = {}): ReleaseDecision {
  return {
    proposal_id: p.proposal_id,
    reviewer_id: w.userId,
    reviewer_role: w.role,
    decision: "accept",
    decided_at: now,
    edited_amount: null,
    edited_due_date: null,
    alternative_action: null,
    override_reason: null,
    second_reviewer_id: null,
    second_reviewer_role: null,
    ...over,
  };
}

// ---------------------------------------------------------------- labels and formatting
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

export const money = (v: string | number, cents = false) =>
  Number(v).toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: cents ? 2 : 0,
    minimumFractionDigits: cents ? 2 : 0,
  });

export const pct = (p: number) => `${Math.round(p * 100)}%`;

export const when = (iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = {}) =>
  iso
    ? new Date(iso).toLocaleString("en-CA", { weekday: "short", hour: "2-digit", minute: "2-digit", ...opts })
    : "";

export const humanize = (s: string) => s.replaceAll("_", " ");

"use client";

import { useState } from "react";
import { ACTION_LABEL, ROLES, api, humanize, type Action, type Proposal, type ReleaseResult, type Role } from "@/lib/api";
import { useIdentity } from "@/lib/identity";
import { Banner, Button, Field, Panel, inputClass } from "./ui";

type Mode = "accept" | "edit" | "alternative" | "override" | "reject";

export function ReviewPanel({ proposal: p, actions }: { proposal: Proposal; actions: Action[] }) {
  const { me } = useIdentity();
  const [mode, setMode] = useState<Mode>("accept");
  const [amount, setAmount] = useState(p.sizing?.amount ?? "");
  const [due, setDue] = useState(p.sizing?.due_date ?? "");
  const [alt, setAlt] = useState<Action | "">("");
  const [reason, setReason] = useState("");
  const [second, setSecond] = useState("");
  const [secondRole, setSecondRole] = useState<Role>("team_lead");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReleaseResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const others = actions.filter((a) => a !== p.action && a !== "wait");
  const invalid =
    (mode === "alternative" && !alt) || (mode === "override" && !reason.trim()) || (p.tier === "red" && !second.trim() && mode !== "reject");

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api.decide({
          proposal_id: p.proposal_id,
          reviewer_id: me.userId,
          reviewer_role: me.role,
          decision: mode,
          decided_at: new Date().toISOString(),
          edited_amount: mode === "edit" && amount !== p.sizing?.amount ? String(amount) : null,
          edited_due_date: mode === "edit" && due !== p.sizing?.due_date ? due : null,
          alternative_action: (mode === "alternative" || mode === "override") && alt ? alt : null,
          override_reason: mode === "override" ? reason.trim() : null,
          second_reviewer_id: second.trim() || null,
          second_reviewer_role: second.trim() ? secondRole : null,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <Panel title="Review">
        <Banner tone={result.released ? "info" : "bad"}>
          <strong className="font-semibold">{result.released ? "Released." : "Not released."}</strong> {result.reason}
        </Banner>
        <p className="mt-2 text-xs text-muted">Logged as {result.audit_event_id}.</p>
      </Panel>
    );
  }

  const MODES: [Mode, string][] = [
    ["accept", "Approve"],
    ...(p.sizing ? ([["edit", "Edit amount"]] as [Mode, string][]) : []),
    ["alternative", "Pick another"],
    ["override", "Override"],
    ["reject", "Reject"],
  ];

  return (
    <Panel title="Review">
      <div role="radiogroup" aria-label="Decision" className="flex flex-wrap gap-1">
        {MODES.map(([m, label]) => (
          <button
            key={m}
            role="radio"
            aria-checked={mode === m}
            onClick={() => setMode(m)}
            className={`rounded-md px-2.5 py-1 text-sm ${mode === m ? "bg-ink text-panel" : "text-muted hover:bg-soft"}`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-4 grid gap-3">
        {mode === "edit" && p.sizing && (
          <div className="grid grid-cols-2 gap-3">
            <Field label={`Amount (max ${p.sizing.spare_cash_estimate})`}>
              <input className={`${inputClass} w-full min-w-0`} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            </Field>
            <Field label="Due date">
              <input className={`${inputClass} w-full min-w-0`} type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </Field>
          </div>
        )}
        {(mode === "alternative" || mode === "override") && (
          <Field label={mode === "override" ? "Action instead (optional)" : "Action instead"}>
            <select className={inputClass} value={alt} onChange={(e) => setAlt(e.target.value as Action | "")}>
              <option value="">{mode === "override" ? `Keep: ${ACTION_LABEL[p.action]}` : "Choose…"}</option>
              {others.map((a) => (
                <option key={a} value={a}>
                  {ACTION_LABEL[a]}
                </option>
              ))}
            </select>
          </Field>
        )}
        {mode === "override" && (
          <Field label="Reason (logged)">
            <textarea className={inputClass} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        )}
        {p.tier === "red" && mode !== "reject" && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Second reviewer">
              <input className={`${inputClass} w-full min-w-0`} value={second} onChange={(e) => setSecond(e.target.value)} placeholder="tl-1" />
            </Field>
            <Field label="Their role">
              <select className={`${inputClass} w-full min-w-0`} value={secondRole} onChange={(e) => setSecondRole(e.target.value as Role)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {humanize(r)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        )}
        {error && <Banner tone="bad">{error}</Banner>}
        <Button variant={mode === "reject" ? "danger" : "primary"} disabled={busy || invalid} onClick={() => void submit()}>
          {busy ? "Checking…" : mode === "reject" ? "Reject proposal" : "Release"}
        </Button>
        <p className="text-xs text-muted">
          {p.tier === "red" && "Red tier: a hardship specialist releases it, with a second person. "}
          {p.tier === "green" && "Green tier: released by a team lead in the daily batch. "}
          Release rechecks hard stops, consent, calling hours and the weekly cap on fresh data.
        </p>
      </div>
    </Panel>
  );
}

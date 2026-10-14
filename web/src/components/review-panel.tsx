"use client";

import { invalidate } from "@/lib/live";
import { InfoCircledIcon } from "@radix-ui/react-icons";
import { Box, Button, Callout, Flex, Select, Text, TextArea, TextField } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { ACTION_LABEL, api, decision, humanize, money, when, type Action, type Proposal, type ReleaseResult } from "@/lib/api";
import { nowIso } from "@/lib/clock";
import type { Persona } from "@/lib/session";
import { Stamp } from "./ledger";
import { spring } from "./motion";

type Mode = "accept" | "edit" | "alternative" | "override" | "reject";
const MODES: { v: Mode; label: string; hint: string }[] = [
  { v: "accept", label: "Approve", hint: "Approve the action as proposed." },
  { v: "edit", label: "Edit", hint: "Change the amount or due date, then approve." },
  { v: "alternative", label: "Other", hint: "Approve a different permitted action instead." },
  { v: "override", label: "Override", hint: "Replace the action and give a reason. The reason is recorded in the audit log." },
  { v: "reject", label: "Reject", hint: "Decline the proposal. Nothing is sent to the customer." },
];

/** Why a proposal of this tier waits for a person. */
const WHY_APPROVAL: Record<Proposal["tier"], string> = {
  red: "This case shows hardship or vulnerability. Only protective actions are proposed, and two people must agree: a hardship specialist first, then a team lead or compliance.",
  amber: "The recommendation needs the assigned agent's judgement before it is sent.",
  green: "Routine contact within every rule. It is released with the team lead's daily batch.",
  blocked: "A hard stop applies (cease request, insolvency or deceased flag). Nothing can be released.",
};

/** A labelled input that slides in after the ones before it (i) when the decision mode changes. */
function Field({ label, i, grow, children }: { label: string; i: number; grow?: boolean; children: React.ReactNode }) {
  return (
    <motion.label
      className="k-field"
      style={grow ? { flex: "1 1 180px" } : undefined}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring, delay: 0.04 + i * 0.06 }}
    >
      <span className="k-field-h">{label}</span>
      {children}
    </motion.label>
  );
}

/** What the reviewer is about to approve, and why their approval is needed, shown before any button. */
function ApprovalBrief({ p }: { p: Proposal }) {
  const s = p.sizing;
  const time = (iso: string) => new Date(iso).toLocaleTimeString("en-CA", { hour: "2-digit", minute: "2-digit" });
  const day = (iso: string) => new Date(iso).toLocaleDateString("en-CA", { weekday: "short" });
  const chips = [
    p.window_start && `${day(p.window_start)} ${time(p.window_start)}${p.window_end ? `–${time(p.window_end)}` : ""}, your time`,
    s && `${money(s.amount, true)}${s.installments > 1 ? ` × ${s.installments}` : ""}, first due ${when(s.due_date, { month: "short", day: "numeric" })}`,
    `Expires ${when(p.expires_at)}`,
  ].filter(Boolean) as string[];
  const tint = { red: "rose", amber: "butter", green: "mint", blocked: "lilac" }[p.tier];
  return (
    <div className={`k-brief t-${tint}`}>
      <span className="k-brief-h">You are approving</span>
      <div className="k-brief-title">
        {ACTION_LABEL[p.action]}
        {p.channel && <span> by {humanize(p.channel).toLowerCase()}</span>}
      </div>
      <div className="k-brief-chips">
        {chips.map((c) => (
          <span key={c} className="tabular">
            {c}
          </span>
        ))}
      </div>
      {s && <p className="k-brief-note">{s.rationale}</p>}
      <div className="k-brief-why">
        <InfoCircledIcon aria-hidden />
        <div>
          <b>Why it needs your approval</b>
          <p>{WHY_APPROVAL[p.tier]}</p>
        </div>
      </div>
      <p className="k-brief-note">The reasons for this action are under “Why this action”. Every rule is checked again at release.</p>
    </div>
  );
}

/** What this persona may do with this proposal right now (the API enforces the same rules). */
function stage(p: Proposal, me: Persona, assignedToMe: boolean): { can: boolean; label: string; note: string } {
  const s = p.status;
  if (s !== "pending" && s !== "approved") return { can: false, label: "", note: `This proposal is ${s}.` };
  if (p.tier === "blocked") return { can: false, label: "", note: "Blocked by a hard stop: nobody can release it." };
  if (p.tier === "red" && s === "pending")
    return me.role === "hardship_specialist"
      ? { can: true, label: "Approve · step 1 of 2", note: "A team lead or compliance gives the second approval." }
      : { can: false, label: "", note: "Red tier: a hardship specialist approves first, then a second person." };
  if (p.tier === "red" && s === "approved")
    return ["team_lead", "compliance", "hardship_specialist"].includes(me.role)
      ? { can: true, label: "Approve · step 2 of 2", note: "Releasing rechecks every safety rule on fresh data." }
      : { can: false, label: "", note: "Approved once; waiting for a second person." };
  if (p.tier === "green")
    return me.role === "team_lead"
      ? { can: true, label: "Release", note: "Green tier: normally released in the daily batch." }
      : { can: false, label: "", note: "Green tier: released by the team lead in the daily batch." };
  return me.role === "agent" && assignedToMe
    ? { can: true, label: "Release", note: "Releasing rechecks hard stops, consent, calling hours and the weekly cap." }
    : { can: false, label: "", note: "Amber tier: the assigned agent releases it." };
}

export function ReviewPanel({
  proposal,
  actions,
  me,
  assignedToMe,
  now,
  onDone,
  presetAmount,
}: {
  proposal: Proposal;
  actions: Action[];
  me: Persona;
  assignedToMe: boolean;
  now: Date | null;
  onDone?: (r: ReleaseResult) => void;
  presetAmount?: string; // from the what-if slider: opens in edit mode with this amount
}) {
  const [p, setP] = useState(proposal);
  const [mode, setMode] = useState<Mode>(presetAmount ? "edit" : "accept");
  const [amount, setAmount] = useState(presetAmount ?? p.sizing?.amount ?? "");
  const [due, setDue] = useState(p.sizing?.due_date ?? "");
  const [alt, setAlt] = useState<Action | "">("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ReleaseResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const st = stage(p, me, assignedToMe);
  const secondStep = p.status === "approved";
  const others = actions.filter((a) => a !== p.action && a !== "wait");
  const invalid = (mode === "alternative" && !alt) || (mode === "override" && !reason.trim());

  async function submit(m: Mode = mode) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.decide(
        decision(p, me, nowIso(now), {
          decision: m,
          edited_amount: m === "edit" && amount !== p.sizing?.amount ? String(amount) : null,
          edited_due_date: m === "edit" && due !== p.sizing?.due_date ? due : null,
          alternative_action: (m === "alternative" || m === "override") && alt ? alt : null,
          override_reason: m === "override" ? reason.trim() : null,
        }),
      );
      setResult(r);
      invalidate("queue:"); // the queue and approvals show the new status next time they load
      invalidate("approvals:");
      invalidate(`card:${p.case_id}:`);
      if (r.reason.startsWith("Approved by")) setP({ ...p, status: "approved" });
      else if (r.released) setP({ ...p, status: "released" });
      else if (m === "reject") setP({ ...p, status: "rejected" });
      onDone?.(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box>
      <AnimatePresence mode="wait">
        {result ? (
          <motion.div key="result" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={spring}>
            <Outcome result={result} />
            {p.status === "approved" && (
              <Text as="p" size="2" color="gray" mt="3">
                It&apos;s now in the team lead&apos;s approvals inbox.
              </Text>
            )}
            {result.released && p.action === "sms_payment_link" && (
              <Button asChild mt="4" variant="soft">
                <a href={`/pay/${encodeURIComponent(p.proposal_id)}`} target="_blank" rel="noreferrer">Customer view: what the SMS opens</a>
              </Button>
            )}
            {!result.released && p.status === "pending" && (
              <Button mt="4" variant="soft" color="gray" onClick={() => setResult(null)}>
                Back to review
              </Button>
            )}
          </motion.div>
        ) : (
          <motion.div key="form" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <ApprovalBrief p={p} />
            {!st.can ? (
              <Callout.Root color="gray" variant="soft">
                <Callout.Text>{st.note}</Callout.Text>
              </Callout.Root>
            ) : (
              <Flex direction="column" gap="3">
                {!secondStep && (
                  <div className="k-modes" role="tablist" aria-label="Decision">
                    {MODES.filter((m) => m.v !== "edit" || p.sizing).map((m) => (
                      <button key={m.v} type="button" role="tab" aria-selected={mode === m.v} data-on={mode === m.v} onClick={() => setMode(m.v)}>
                        {mode === m.v && <motion.span layoutId={`mode-${p.proposal_id}`} className="k-modes-pill" transition={spring} />}
                        <span>{m.label}</span>
                      </button>
                    ))}
                  </div>
                )}
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.div key={mode} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
                    <Flex direction="column" gap="3">
                      {!secondStep && <p className="k-mode-hint">{MODES.find((m) => m.v === mode)?.hint}</p>}
                      {mode === "edit" && p.sizing && (
                        <Flex gap="3" wrap="wrap">
                          <Field label={`Amount · at most ${money(p.sizing.spare_cash_estimate, true)}`} i={0} grow>
                            <TextField.Root size="3" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
                          </Field>
                          <Field label="Due date" i={1} grow>
                            <TextField.Root size="3" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
                          </Field>
                        </Flex>
                      )}
                      {(mode === "alternative" || mode === "override") && (
                        <Field label={mode === "override" ? "Action to send instead" : "Permitted alternative"} i={0}>
                          <Select.Root size="3" value={alt || "keep"} onValueChange={(v) => setAlt(v === "keep" ? "" : (v as Action))}>
                            <Select.Trigger className="k-select" placeholder="Choose an action" />
                            <Select.Content position="popper" sideOffset={6} className="k-select-menu">
                              {mode === "override" && <Select.Item value="keep">Keep: {ACTION_LABEL[p.action]}</Select.Item>}
                              {others.map((a) => (
                                <Select.Item key={a} value={a}>
                                  {ACTION_LABEL[a]}
                                </Select.Item>
                              ))}
                            </Select.Content>
                          </Select.Root>
                        </Field>
                      )}
                      {mode === "override" && (
                        <Field label="Reason · recorded in the audit log" i={1}>
                          <TextArea
                            size="3"
                            rows={3}
                            className="k-textarea"
                            placeholder="Why the proposed action should not be sent"
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                          />
                        </Field>
                      )}
                    </Flex>
                  </motion.div>
                </AnimatePresence>
                {error && (
                  <Callout.Root color="red" size="1">
                    <Callout.Text>{error}</Callout.Text>
                  </Callout.Root>
                )}
                <Flex gap="2">
                  <Button size="3" style={{ flex: 1 }} loading={busy} disabled={invalid} color={mode === "reject" ? "gray" : undefined} onClick={() => void submit()}>
                    {mode === "reject" ? "Reject proposal" : st.label}
                  </Button>
                  {secondStep && (
                    <Button size="3" variant="soft" color="gray" disabled={busy} onClick={() => void submit("reject")}>
                      Reject
                    </Button>
                  )}
                </Flex>
                <Text size="1" color="gray">{st.note}</Text>
              </Flex>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </Box>
  );
}

function Outcome({ result }: { result: ReleaseResult }) {
  const waiting = result.reason.startsWith("Approved by");
  return (
    <Flex direction="column" align="center" gap="3" py="4" style={{ textAlign: "center" }}>
      <Stamp
        text={result.released ? "Released" : waiting ? "Approved" : "Not released"}
        sub={result.released ? "rechecked on fresh data" : waiting ? "1 of 2 · needs a second person" : "the gate said no"}
        ink={result.released ? "grass" : waiting ? "amber" : "red"}
        size={1.1}
      />
      <Text size="2" color="gray" mt="2">{result.reason}</Text>
      <Text size="1" color="gray" className="tabular">Audit {result.audit_event_id}</Text>
    </Flex>
  );
}

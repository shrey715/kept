"use client";

import { Box, Button, Callout, Flex, SegmentedControl, Select, Text, TextArea, TextField } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { ACTION_LABEL, api, decision, type Action, type Proposal, type ReleaseResult } from "@/lib/api";
import { nowIso } from "@/lib/clock";
import type { Persona } from "@/lib/session";
import { Stamp } from "./ledger";
import { spring } from "./motion";

type Mode = "accept" | "edit" | "alternative" | "override" | "reject";

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
      : { can: false, label: "", note: "Green tier: the team lead releases it in the daily batch." };
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
            {!st.can ? (
              <Callout.Root color="gray" variant="soft">
                <Callout.Text>{st.note}</Callout.Text>
              </Callout.Root>
            ) : (
              <Flex direction="column" gap="3">
                {!secondStep && (
                  <SegmentedControl.Root value={mode} onValueChange={(v) => setMode(v as Mode)} size="1">
                    <SegmentedControl.Item value="accept">Approve</SegmentedControl.Item>
                    {p.sizing && <SegmentedControl.Item value="edit">Edit</SegmentedControl.Item>}
                    <SegmentedControl.Item value="alternative">Other</SegmentedControl.Item>
                    <SegmentedControl.Item value="override">Override</SegmentedControl.Item>
                    <SegmentedControl.Item value="reject">Reject</SegmentedControl.Item>
                  </SegmentedControl.Root>
                )}
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.div key={mode} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }}>
                    <Flex direction="column" gap="3">
                      {mode === "edit" && p.sizing && (
                        <Flex gap="3">
                          <label style={{ flex: 1 }}>
                            <Text size="1" color="gray">Amount (max {p.sizing.spare_cash_estimate})</Text>
                            <TextField.Root inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
                          </label>
                          <label style={{ flex: 1 }}>
                            <Text size="1" color="gray">Due date</Text>
                            <TextField.Root type="date" value={due} onChange={(e) => setDue(e.target.value)} />
                          </label>
                        </Flex>
                      )}
                      {(mode === "alternative" || mode === "override") && (
                        <Select.Root value={alt || "keep"} onValueChange={(v) => setAlt(v === "keep" ? "" : (v as Action))}>
                          <Select.Trigger placeholder="Choose an action" />
                          <Select.Content>
                            {mode === "override" && <Select.Item value="keep">Keep: {ACTION_LABEL[p.action]}</Select.Item>}
                            {others.map((a) => (
                              <Select.Item key={a} value={a}>
                                {ACTION_LABEL[a]}
                              </Select.Item>
                            ))}
                          </Select.Content>
                        </Select.Root>
                      )}
                      {mode === "override" && (
                        <TextArea placeholder="Reason (goes in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
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

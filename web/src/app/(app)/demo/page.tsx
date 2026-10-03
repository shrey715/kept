"use client";

import { ArrowLeftIcon, ArrowRightIcon, CheckIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Callout, Card, Code, Flex, Grid, Heading, Kbd, Text, TextArea } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { AuditTimeline } from "@/components/audit-timeline";
import { CustomerPanel } from "@/components/customer-panel";
import { spring } from "@/components/motion";
import { NbaCard } from "@/components/nba-card";
import { api, decision, type AskResponse, type AuditEvent, type Customer, type NBACard, type ReleaseResult } from "@/lib/api";
import { nowIso, useServerClock } from "@/lib/clock";
import { PERSONAS } from "@/lib/session";

const as = (id: string) => PERSONAS.find((p) => p.userId === id)!;
const AGENT_PERSONA = as("agent-7"), SPECIALIST = as("hs-1"), LEAD = as("tl-1"), COMPLIANCE = as("c-1"), ANALYST = as("an-1");
// `kept serve --demo` has a made-up case; real data only shows a case to its assigned agent, so the guide
// uses a real open case and its agent there (the "new note flips hardship" case checked at G3).
const DEMO_CASE = { caseId: "CS-2026-118204", agent: AGENT_PERSONA };
const REAL_CASE = { caseId: "CS-2026-820205", agent: { ...AGENT_PERSONA, userId: "AG-8365" } };

const STEPS = [
  { title: "One customer, one ID", who: COMPLIANCE, says: "Five systems each keep their own customer key. Kept resolves them to one golden ID, with the weakest match shown." },
  { title: "Ask in plain English", who: ANALYST, says: "A certified metric answered with its SQL, and a question about a protected attribute refused with a safer suggestion." },
  { title: "The next best action", who: AGENT_PERSONA, says: "Rules first, then the model: a call in the customer's own calling hours, with the three reasons that drove it." },
  { title: "A new note changes everything", who: AGENT_PERSONA, says: "The agent logs that shifts were cut. Hardship turns possible, aggressive actions drop out, and the case goes Red." },
  { title: "Two people release it", who: SPECIALIST, says: "A hardship specialist approves first, a team lead second. Every safety rule is rechecked at release." },
  { title: "Every step on the record", who: COMPLIANCE, says: "The audit trail shows each recommendation, the hardship change, and both approvals." },
];

export default function DemoPage() {
  const { now, health } = useServerClock();
  const { caseId: CASE, agent: AGENT } = health?.demo === false ? REAL_CASE : DEMO_CASE;
  const [step, setStep] = useState(0);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [answers, setAnswers] = useState<AskResponse[]>([]);
  const [card, setCard] = useState<NBACard | null>(null);
  const [note, setNote] = useState("Customer says shifts were cut at the plant since August; can't afford the full amount.");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<ReleaseResult[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, []);

  // load what each step shows when it opens (state is set only when a request resolves)
  useEffect(() => {
    if (!health) return; // wait for the server's mode: it picks the case
    let live = true;
    const job =
      step === 0 && !customer
        ? api.customer(CASE, COMPLIANCE).then((c) => live && setCustomer(c))
        : step === 1 && !answers.length
          ? Promise.all([
              api.ask("What is the promise kept rate by product for the last 90 days?", ANALYST),
              api.ask("What is the kept rate by gender?", ANALYST),
            ]).then((a) => live && setAnswers(a))
          : step === 2 && !card
            ? api.card(CASE, AGENT).then((c) => live && setCard(c))
            : step === 5
              ? api.audit(COMPLIANCE, { caseId: CASE }).then((e) => live && setEvents(e))
              : null;
    job?.catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [step, customer, answers.length, card, health, CASE, AGENT]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      if (e.key === "ArrowRight") setStep((s) => Math.min(s + 1, STEPS.length - 1));
      if (e.key === "ArrowLeft") setStep((s) => Math.max(s - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const approve = (who: typeof SPECIALIST) =>
    run(async () => {
      const fresh = card?.proposal ? card : await api.card(CASE, AGENT);
      if (!fresh.proposal) throw new Error(fresh.no_action_reason ?? "no proposal to release");
      const r = await api.decide(decision(fresh.proposal, who, nowIso(now)));
      setResults((rs) => [...rs, r]);
    });

  const s = STEPS[step];
  return (
    <Grid columns={{ initial: "1", md: "280px 1fr" }} gap="6">
      <Box>
        <Text size="1" weight="bold" color="ruby">GUIDED DEMO</Text>
        <Heading size="6" mt="1" mb="4">Jane&apos;s case, start to finish</Heading>
        <Flex direction="column" gap="1" position="relative">
          {STEPS.map((st, i) => (
            <button key={st.title} onClick={() => setStep(i)} style={{ all: "unset", cursor: "pointer", position: "relative" }}>
              {i === step && (
                <motion.div layoutId="demo-step" transition={spring} style={{ position: "absolute", inset: 0, borderRadius: "var(--radius-3)", background: "var(--accent-a3)" }} />
              )}
              <Flex gap="3" align="center" p="2" style={{ position: "relative" }}>
                <Flex align="center" justify="center" style={{ width: 24, height: 24, borderRadius: 999, flexShrink: 0, background: i < step ? "var(--accent-9)" : "var(--gray-a3)", color: i < step ? "white" : "var(--gray-11)", transition: "background 200ms" }}>
                  {i < step ? <CheckIcon /> : <Text size="1" weight="bold">{i + 1}</Text>}
                </Flex>
                <Text size="2" weight={i === step ? "bold" : "regular"} color={i === step ? undefined : "gray"}>{st.title}</Text>
              </Flex>
            </button>
          ))}
        </Flex>
        <Text as="p" size="1" color="gray" mt="4"><Kbd><ArrowLeftIcon aria-label="left arrow" /></Kbd> <Kbd><ArrowRightIcon aria-label="right arrow" /></Kbd> to move between steps</Text>
      </Box>

      <Box>
        <AnimatePresence mode="wait">
          <motion.div key={step} initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }} transition={spring}>
            <Flex align="center" gap="2" mb="2">
              <Badge variant="soft" radius="full">Step {step + 1} of {STEPS.length}</Badge>
              <Badge variant="outline" color="gray" radius="full">as {s.who.name} · {s.who.title}</Badge>
            </Flex>
            <Heading size="8">{s.title}</Heading>
            <Text as="p" size="4" color="gray" mt="2" mb="5" style={{ maxWidth: 720 }}>{s.says}</Text>
            {error && <Callout.Root color="red" mb="4"><Callout.Text>{error}</Callout.Text></Callout.Root>}

            {step === 0 && customer && (
              <Grid columns={{ initial: "1", lg: "1fr 1fr" }} gap="4">
                <Card size="3"><Convergence c={customer} /></Card>
                <Card size="3"><CustomerPanel c={customer} /></Card>
              </Grid>
            )}
            {step === 1 && (
              <Flex direction="column" gap="3">
                {answers.map((a, i) => (
                  <motion.div key={i} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: i * 0.25 }}>
                    <Card size="3">
                      {a.kind === "answer" && (
                        <>
                          <Text as="p" size="5" className="serif" weight="medium">{a.narrative}</Text>
                          <Code variant="soft" style={{ display: "block", whiteSpace: "pre-wrap", padding: 12, marginTop: 12 }}>{a.sql}</Code>
                        </>
                      )}
                      {a.kind === "refusal" && (
                        <Callout.Root color="amber"><Callout.Text><Text weight="bold">Refused.</Text> {a.message} {a.suggestion}</Callout.Text></Callout.Root>
                      )}
                      {a.kind === "clarification" && <Text>{a.question}</Text>}
                    </Card>
                  </motion.div>
                ))}
              </Flex>
            )}
            {(step === 2 || step === 3) && card && (
              <Grid columns={{ initial: "1", lg: step === 3 ? "1fr 340px" : "1fr" }} gap="4" align="start">
                <NbaCard card={card} />
                {step === 3 && (
                  <Card size="3">
                    <Heading size="4" mb="3">Agent note</Heading>
                    <TextArea rows={5} value={note} onChange={(e) => setNote(e.target.value)} />
                    <Button mt="3" size="3" style={{ width: "100%" }} loading={busy} onClick={() => void run(async () => setCard(await api.note(CASE, note, AGENT)))}>
                      Save note and re-check
                    </Button>
                  </Card>
                )}
              </Grid>
            )}
            {step === 4 && (
              <Grid columns={{ initial: "1", sm: "1fr 1fr" }} gap="4">
                {[SPECIALIST, LEAD].map((who, i) => {
                  const r = results[i];
                  return (
                    <Card key={who.userId} size="3">
                      <Text size="1" color="gray" weight="bold">STEP {i + 1} OF 2</Text>
                      <Heading size="5" mt="1">{who.name}</Heading>
                      <Text size="2" color="gray">{who.title}</Text>
                      <Box mt="4">
                        {r ? (
                          <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={spring}>
                            <Badge size="3" color={r.released ? "grass" : r.reason.startsWith("Approved") ? "amber" : "red"}>
                              {r.released ? "Released" : r.reason.startsWith("Approved") ? "Approved · 1 of 2" : "Not released"}
                            </Badge>
                            <Text as="p" size="2" color="gray" mt="2">{r.reason}</Text>
                          </motion.div>
                        ) : (
                          <Button size="3" disabled={busy || results.length !== i} loading={busy && results.length === i} onClick={() => void approve(who)}>
                            Approve as {who.name.split(" ")[0]}
                          </Button>
                        )}
                      </Box>
                    </Card>
                  );
                })}
              </Grid>
            )}
            {step === 5 && <Card size="3"><AuditTimeline events={events} /></Card>}

            <Flex justify="between" mt="6">
              <Button variant="soft" color="gray" disabled={step === 0} onClick={() => setStep(step - 1)}><ArrowLeftIcon /> Back</Button>
              {step < STEPS.length - 1 && <Button onClick={() => setStep(step + 1)}>Next <ArrowRightIcon /></Button>}
            </Flex>
          </motion.div>
        </AnimatePresence>
      </Box>
    </Grid>
  );
}

/** Source keys fly in from the edges and merge into the golden ID. */
function Convergence({ c }: { c: Customer }) {
  const n = c.source_keys.length;
  return (
    <Box position="relative" style={{ height: 300 }}>
      <svg width="100%" height="100%" viewBox="0 0 400 300" aria-hidden style={{ position: "absolute", inset: 0 }}>
        {c.source_keys.map((_, i) => {
          const a = (i / n) * Math.PI * 2 - Math.PI / 2;
          return (
            <motion.line key={i} x1={200 + Math.cos(a) * 130} y1={150 + Math.sin(a) * 110} x2="200" y2="150" stroke="var(--accent-a7)" strokeWidth="2" strokeDasharray="4 4"
              initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: 0.5 + i * 0.15, duration: 0.6 }} />
          );
        })}
      </svg>
      {c.source_keys.map((k, i) => {
        const a = (i / n) * Math.PI * 2 - Math.PI / 2;
        return (
          <motion.div key={k.key} initial={{ opacity: 0, x: Math.cos(a) * 240, y: Math.sin(a) * 200 }} animate={{ opacity: 1, x: Math.cos(a) * 130, y: Math.sin(a) * 110 }} transition={{ ...spring, delay: i * 0.12 }}
            style={{ position: "absolute", left: "50%", top: "50%", translate: "-50% -50%" }}>
            <Badge size="2" variant="surface" style={{ whiteSpace: "nowrap" }}>{k.system} · {k.key}</Badge>
          </motion.div>
        );
      })}
      <motion.div initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ ...spring, delay: 1.2 }} style={{ position: "absolute", left: "50%", top: "50%", translate: "-50% -50%" }}>
        <motion.div animate={{ boxShadow: ["0 0 0 0 var(--accent-a6)", "0 0 0 18px transparent"] }} transition={{ repeat: Infinity, duration: 1.8, delay: 1.6 }}
          style={{ borderRadius: 999, background: "var(--accent-9)", color: "white", padding: "12px 18px" }}>
          <Text weight="bold" className="tabular">{c.golden_customer_id}</Text>
        </motion.div>
      </motion.div>
    </Box>
  );
}

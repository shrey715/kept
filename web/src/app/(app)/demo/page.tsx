"use client";

import { SectionTitle } from "@/components/page-header";
import { ArrowLeftIcon, ArrowRightIcon, ChatBubbleIcon, CheckIcon, PauseIcon, PlayIcon, ReloadIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Callout, Card, Flex, Grid, Heading, Text, TextArea, TextField } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { AuditTimeline } from "@/components/audit-timeline";
import { CitedText, Sources, useVerify } from "@/components/citations";
import { PipelineCanvas, type NodeId } from "@/components/pipeline-canvas";
import { CustomerPanel } from "@/components/customer-panel";
import { spring } from "@/components/motion";
import { NbaCard } from "@/components/nba-card";
import { api, decision, type AskResponse, type AuditEvent, type Customer, type NBACard, type ReleaseResult } from "@/lib/api";
import { nowIso, useServerClock } from "@/lib/clock";
import { PERSONAS, REAL_USER_IDS } from "@/lib/session";

const as = (id: string) => PERSONAS.find((p) => p.userId === id)!;
const AGENT_PERSONA = as("agent-7"), SPECIALIST = as("hs-1"), LEAD = as("tl-1"), COMPLIANCE = as("c-1"), ANALYST = as("an-1");
// `kept serve --demo` has a made-up case; real data only shows a case to its assigned agent, so the guide
// uses a real open case and its agent there (the "new note flips hardship" case checked at G3).
const DEMO_CASE = { caseId: "CS-2026-118204", agent: AGENT_PERSONA };
const REAL_CASE = { caseId: "CS-2026-820205", agent: { ...AGENT_PERSONA, userId: REAL_USER_IDS["agent-7"] } };

const QUESTIONS = ["What is the promise kept rate by product for the last 90 days?", "What is the kept rate by gender?"];

const STEPS: { title: string; who: typeof COMPLIANCE; says: string; nodes: NodeId[] }[] = [
  { title: "Identity resolution", who: COMPLIANCE, nodes: ["sources", "identity"], says: "Five source systems each hold their own customer key. They are resolved to one golden ID, with the weakest match shown." },
  { title: "Ask a question", who: ANALYST, nodes: ["sources", "identity", "features", "ask"], says: "A certified metric is answered with its query and sources; a question about a protected attribute is refused with a suggested alternative." },
  { title: "Next best action", who: AGENT_PERSONA, nodes: ["features", "models", "decide"], says: "Rules run first, then the models: a contact inside the customer's permitted hours, with the factors behind it." },
  { title: "A note updates the case", who: AGENT_PERSONA, nodes: ["notes", "features", "models", "decide"], says: "The agent records that the customer's hours were cut. Hardship becomes possible, intensive actions are removed and the case moves to Red." },
  { title: "Two-person release", who: SPECIALIST, nodes: ["decide", "release"], says: "A hardship specialist approves first and a team lead second. Every safety rule is rechecked at release." },
  { title: "Audit trail", who: COMPLIANCE, nodes: ["release", "audit"], says: "Each recommendation, the hardship change and both approvals are recorded in the hash-chained log." },
];
const STEP_OF: Record<NodeId, number> = { sources: 0, identity: 0, ask: 1, features: 2, models: 2, decide: 2, notes: 3, release: 4, audit: 5 };
const PLAY_MS = 6500; // each step's time on screen when the demo runs by itself

export default function DemoPage() {
  const { now, health } = useServerClock();
  const { caseId: CASE, agent: AGENT } = health?.demo === false ? REAL_CASE : DEMO_CASE;
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [answers, setAnswers] = useState<{ q: string; r: AskResponse }[]>([]);
  const [own, setOwn] = useState("");
  const [nonce, setNonce] = useState(0); // bumped by Retry: reloads the open step
  const [verify, verifyDialog] = useVerify();
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
          ? Promise.all(QUESTIONS.map((q) => api.ask(q, ANALYST))).then((a) => live && setAnswers(a.map((r, i) => ({ q: QUESTIONS[i], r }))))
          : step >= 2 && step <= 4 && !card
            ? api.card(CASE, AGENT).then((c) => live && setCard(c))
            : step === 5
              ? api.audit(COMPLIANCE, { caseId: CASE }).then((e) => live && setEvents(e))
              : null;
    job?.catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [step, customer, answers.length, card, health, CASE, AGENT, nonce]);

  // Retry: drop what the open step loaded (or half-loaded) and fetch it again
  const retry = () => {
    setError(null);
    if (step === 0) setCustomer(null);
    if (step === 1) setAnswers([]);
    if (step >= 2 && step <= 4) {
      setCard(null);
      setResults([]);
    }
    setNonce((n) => n + 1);
  };
  const askOwn = (q: string) =>
    run(async () => {
      const r = await api.ask(q, ANALYST);
      setAnswers((a) => [...a, { q, r }]);
      setOwn("");
    });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement) return;
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") setPlaying(false);
      if (e.key === "ArrowRight") setStep((s) => Math.min(s + 1, STEPS.length - 1));
      if (e.key === "ArrowLeft") setStep((s) => Math.max(s - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Run the case: the demo plays itself, one step every PLAY_MS; any manual move stops it
  useEffect(() => {
    if (!playing) return;
    const t = setTimeout(() => {
      if (step >= STEPS.length - 1) setPlaying(false);
      else setStep(step + 1);
    }, PLAY_MS);
    return () => clearTimeout(t);
  }, [playing, step]);
  const pick = (i: number) => {
    setPlaying(false);
    setStep(i);
  };

  const approve = (who: typeof SPECIALIST) =>
    run(async () => {
      const fresh = card?.proposal ? card : await api.card(CASE, AGENT);
      if (!fresh.proposal) throw new Error(fresh.no_action_reason ?? "no proposal to release");
      const r = await api.decide(decision(fresh.proposal, who, nowIso(now)));
      setResults((rs) => [...rs, r]);
    });

  const s = STEPS[step];
  return (
    <Box>
      <Flex justify="between" align="end" gap="4" wrap="wrap" mb="4">
        <SectionTitle eyebrow="Guided demo" title="One case, start to finish" icon={<PlayIcon />} mb="0" />
        <button
          className="k-run"
          onClick={() => {
            if (playing) return setPlaying(false);
            if (step === STEPS.length - 1) setStep(0);
            setPlaying(true);
          }}
        >
          <span className="ring">{playing ? <PauseIcon /> : <PlayIcon />}</span>
          {playing ? "Pause" : step === STEPS.length - 1 ? "Run again" : "Run the case"}
        </button>
      </Flex>
      <div className="k-demo-steps" role="tablist" aria-label="Steps">
        {STEPS.map((st, i) => (
          <button key={st.title} role="tab" aria-selected={i === step} className="k-demo-step" data-state={i < step ? "done" : i === step ? "now" : "next"} onClick={() => pick(i)}>
            {i === step && <motion.span layoutId="demo-step" className="k-demo-step-bg" transition={spring} />}
            <span className="num">{i < step ? <CheckIcon /> : i + 1}</span>
            <span className="txt">{st.title}</span>
            {i === step && playing && (
              <motion.span key={`p${step}`} className="bar" initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: PLAY_MS / 1000, ease: "linear" }} />
            )}
          </button>
        ))}
      </div>
      <div className="k-pipe-scroll" style={{ margin: "14px 0 22px" }}>
        <PipelineCanvas active={STEPS[step].nodes} onPick={(id) => pick(STEP_OF[id])} />
      </div>

      <Box>
        <AnimatePresence mode="wait">
          <motion.div key={step} initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }} transition={spring}>
            <Flex align="center" gap="2" mb="2">
              <span className="k-badge" style={{ background: "var(--k-hi)", color: "var(--k-hi-ink)", height: 28, borderRadius: 999, padding: "0 10px" }}>
                Step {step + 1} of {STEPS.length}
              </span>
              <span className="k-badge" style={{ height: 28, borderRadius: 999, padding: "0 10px" }}>
                as {s.who.name} · {s.who.title}
              </span>
            </Flex>
            <Heading size="8">{s.title}</Heading>
            <Text as="p" size="4" color="gray" mt="2" mb="5" style={{ maxWidth: 720 }}>{s.says}</Text>
            {error && (
              <Callout.Root color="red" mb="4">
                <Callout.Text>
                  {error}{" "}
                  <Button size="1" variant="soft" color="red" ml="2" onClick={retry}><ReloadIcon /> Retry</Button>
                </Callout.Text>
              </Callout.Root>
            )}

            {step === 0 && customer && (
              <Grid columns={{ initial: "1", lg: "1fr 1fr" }} gap="4">
                <Card size="3" className="k-dots"><Convergence c={customer} /></Card>
                <Card size="3"><CustomerPanel c={customer} /></Card>
              </Grid>
            )}
            {step === 1 && (
              <Flex direction="column" gap="3">
                {answers.map(({ q, r: a }, i) => (
                  <motion.div key={`${i}-${q}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: i < 2 ? i * 0.25 : 0 }}>
                    <Card size="3">
                      <Flex align="center" gap="2" mb="3">
                        <ChatBubbleIcon />
                        <Text size="2" color="gray">{ANALYST.name.split(" ")[0]} asks</Text>
                        <Text size="2" weight="medium">“{q}”</Text>
                      </Flex>
                      {a.kind === "answer" && (
                        <>
                          <CitedText text={a.narrative} citations={a.citations} onOpen={verify} />
                          <Sources r={a} onOpen={verify} />
                        </>
                      )}
                      {a.kind === "refusal" && (
                        <Callout.Root color="amber">
                          <Callout.Text>
                            <Text weight="bold">Refused.</Text> {a.message}
                          </Callout.Text>
                          {a.suggestion && (
                            <Box>
                              <Button size="1" variant="soft" color="amber" disabled={busy} onClick={() => void askOwn(a.suggestion!.replace(/^Try:\s*/, ""))}>{a.suggestion}</Button>
                            </Box>
                          )}
                        </Callout.Root>
                      )}
                      {a.kind === "clarification" && <Callout.Root color="gray"><Callout.Text>{a.question}</Callout.Text></Callout.Root>}
                    </Card>
                  </motion.div>
                ))}
                {answers.length > 0 && (
                  <Card size="2">
                    <form onSubmit={(e) => { e.preventDefault(); if (own.trim()) void askOwn(own); }}>
                      <Flex gap="2">
                        <TextField.Root style={{ flex: 1 }} placeholder="Ask your own: a metric, a policy, or try a protected attribute" value={own} onChange={(e) => setOwn(e.target.value)} aria-label="Your question" />
                        <Button loading={busy} disabled={!own.trim()}>Ask</Button>
                      </Flex>
                    </form>
                  </Card>
                )}
              </Flex>
            )}
            {(step === 2 || step === 3) && card && (
              <Grid columns={{ initial: "1", lg: step === 3 ? "1fr 340px" : "1fr" }} gap="4" align="start">
                <NbaCard card={card} />
                {step === 3 && (
                  <Card size="3" className="t-butter">
                    <SectionTitle eyebrow="Step 4" title="Agent note" mb="3" />
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
                    <Card key={who.userId} size="3" className={r?.released ? "t-mint" : "t-rose"}>
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
            {(step === 3 || step === 4) && card && (
              <Flex justify="end" mt="3">
                <Button size="1" variant="ghost" color="gray" onClick={retry}><ReloadIcon /> Reload the case</Button>
              </Flex>
            )}

            <Flex justify="between" mt="6">
              <button className="k-tab" style={{ height: 44 }} disabled={step === 0} onClick={() => setStep(step - 1)}>
                <ArrowLeftIcon /> Back
              </button>
              {step < STEPS.length - 1 && (
                <button className="k-strong-btn" onClick={() => setStep(step + 1)}>
                  Next <ArrowRightIcon />
                </button>
              )}
            </Flex>
          </motion.div>
        </AnimatePresence>
        {verifyDialog}
      </Box>
    </Box>
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
          <motion.div key={`${k.system}-${k.key}`} initial={{ opacity: 0, x: Math.cos(a) * 240, y: Math.sin(a) * 200 }} animate={{ opacity: 1, x: Math.cos(a) * 130, y: Math.sin(a) * 110 }} transition={{ ...spring, delay: i * 0.12 }}
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

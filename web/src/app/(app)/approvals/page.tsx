"use client";

import { CheckCircledIcon, LightningBoltIcon, PersonIcon, StackIcon } from "@radix-ui/react-icons";
import { Badge, Box, Button, Callout, Card, Dialog, Flex, Grid, Progress, Skeleton, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { TierBadge } from "@/components/bits";
import { CountUp, Rise, Stagger, spring } from "@/components/motion";
import { PageHeader } from "@/components/page-header";
import { ReviewPanel } from "@/components/review-panel";
import { ACTION_LABEL, api, decision, money, when, type ApprovalItem } from "@/lib/api";
import { nowIso, useServerClock } from "@/lib/clock";
import { useSession } from "@/lib/session";

const STAGE_ICON: Record<ApprovalItem["stage"], React.ReactNode> = {
  specialist: <PersonIcon />,
  second_person: <CheckCircledIcon />,
  green_batch: <StackIcon />,
  assigned_agent: <LightningBoltIcon />,
};
const CONCURRENCY = 6; // the green batch releases this many at once; each release re-runs every check

const STAGES: Record<ApprovalItem["stage"], { label: string; blurb: string }> = {
  specialist: { label: "Red · first approval", blurb: "Hardship and vulnerability cases. You approve first; a second person releases." },
  second_person: { label: "Red · second approval", blurb: "A specialist has approved these. Your approval releases them after a fresh safety check." },
  green_batch: { label: "Green batch", blurb: "Template reminders and payment links. Sample 20, then release the batch." },
  assigned_agent: { label: "My Amber cases", blurb: "Calls, promises and plans on your own cases." },
};

export default function ApprovalsPage() {
  const { me } = useSession();
  const { now } = useServerClock();
  const [items, setItems] = useState<ApprovalItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<ApprovalItem | null>(null);
  const [picked, setPicked] = useState<ApprovalItem["stage"] | null>(null);

  const load = useCallback(() => {
    if (me) api.approvals(me).then(setItems, (e: Error) => setError(e.message));
  }, [me]);
  useEffect(() => {
    load();
  }, [load]);

  const byStage = useMemo(() => {
    const m = new Map<ApprovalItem["stage"], ApprovalItem[]>();
    (items ?? []).forEach((i) => m.set(i.stage, [...(m.get(i.stage) ?? []), i]));
    return m;
  }, [items]);
  const stages = [...byStage.keys()];
  const stage = picked && byStage.has(picked) ? picked : stages[0];

  if (!me) return null;
  return (
    <Stagger>
      <Rise>
        <PageHeader
          icon={<CheckCircledIcon />}
          eyebrow="Approvals"
          title="Nothing reaches a customer until the right person releases it."
          sub="Each release re-runs every safety check on fresh data. Red needs a specialist and a second person."
        />
      </Rise>
      {error && (
        <Callout.Root color="red" mt="4">
          <Callout.Text>{error}</Callout.Text>
        </Callout.Root>
      )}
      {!items && !error && <Skeleton height="240px" mt="5" />}
      {items && items.length === 0 && (
        <Rise>
          <div className="k-card" style={{ padding: 40 }}>
            <Flex direction="column" align="center" gap="3">
              <span className="k-chip" style={{ width: 56, height: 56, borderRadius: 18, color: "var(--grass-10)" }}>
                <CheckCircledIcon width={22} height={22} />
              </span>
              <Text size="7" style={{ letterSpacing: "-0.03em" }}>Inbox zero</Text>
              <Text color="gray" size="2">Nothing is waiting for {me.title.toLowerCase()} approval.</Text>
            </Flex>
          </div>
        </Rise>
      )}
      {stages.length > 0 && stage && (
        <>
          <Grid columns={{ initial: "1", sm: String(Math.min(stages.length, 4)) }} gap="3">
            {stages.map((st) => (
              <Rise key={st}>
                <motion.button
                  className={`k-card k-link${st === stage ? " hi" : ""}`}
                  style={{ border: 0, width: "100%", textAlign: "left", cursor: "pointer", font: "inherit", color: "inherit" }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => setPicked(st)}
                  aria-pressed={st === stage}
                >
                  <Flex align="center" gap="3">
                    <span className="k-chip" style={st === stage ? { background: "var(--k-hi-chip)", color: "var(--k-hi-ink)" } : undefined}>
                      {STAGE_ICON[st]}
                    </span>
                    <Text size="2" weight="medium">
                      {STAGES[st].label}
                    </Text>
                  </Flex>
                  <div className="k-big" style={{ marginTop: 14 }}>
                    <CountUp value={byStage.get(st)!.length} format={(n) => Math.round(n).toString()} />
                  </div>
                </motion.button>
              </Rise>
            ))}
          </Grid>
          <AnimatePresence mode="wait">
            <motion.div key={stage} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
              <Text as="p" size="2" color="gray" my="4">
                {STAGES[stage].blurb}
              </Text>
              {stage === "green_batch" ? (
                <GreenBatch items={byStage.get(stage)!} now={now} onDone={load} />
              ) : (
                <Flex direction="column" gap="3">
                  <AnimatePresence initial={false}>
                    {byStage.get(stage)!.map((a, i) => (
                      <motion.div
                        key={a.proposal.proposal_id}
                        layout
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0, transition: { ...spring, delay: Math.min(i, 12) * 0.04 } }}
                        exit={{ opacity: 0, x: 40 }}
                        style={{ contentVisibility: "auto", containIntrinsicSize: "auto 88px" }}
                      >
                        <ApprovalRow item={a} onOpen={() => setOpen(a)} />
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </Flex>
              )}
            </motion.div>
          </AnimatePresence>
        </>
      )}

      <Dialog.Root open={!!open} onOpenChange={(o) => { if (!o) { setOpen(null); load(); } }}>
        <Dialog.Content maxWidth="480px">
          {open && (
            <>
              <Dialog.Title>{ACTION_LABEL[open.proposal.action]}</Dialog.Title>
              <Dialog.Description size="2" color="gray" mb="4">
                Case {open.proposal.case_id}
                {open.first_approver && ` · first approval by ${open.first_approver}`}
              </Dialog.Description>
              <ReviewPanel proposal={open.proposal} actions={[open.proposal.action]} me={me} assignedToMe={open.stage === "assigned_agent"} now={now} />
              <Flex justify="end" mt="4">
                <Dialog.Close>
                  <Button variant="soft" color="gray">Close</Button>
                </Dialog.Close>
              </Flex>
            </>
          )}
        </Dialog.Content>
      </Dialog.Root>
    </Stagger>
  );
}

function ApprovalRow({ item, onOpen }: { item: ApprovalItem; onOpen: () => void }) {
  const p = item.proposal;
  return (
    <Card size="2">
      <Flex align="center" gap="4" wrap="wrap">
        <Box style={{ flex: 1, minWidth: 240 }}>
          <Flex align="center" gap="2" wrap="wrap">
            <TierBadge tier={p.tier} long={false} />
            <Text weight="bold">{ACTION_LABEL[p.action]}</Text>
            {p.sizing && <Text color="gray">· {money(p.sizing.amount)} × {p.sizing.installments}</Text>}
          </Flex>
          <Text as="div" size="1" color="gray" mt="1" className="tabular">
            <Link href={`/cases/${p.case_id}`}>{p.case_id}</Link>
            {p.window_start && ` · ${when(p.window_start)}`} · expires {when(p.expires_at)}
            {item.first_approver && ` · approved by ${item.first_approver}`}
          </Text>
        </Box>
        <Button onClick={onOpen}>{item.stage === "second_person" ? "Give second approval" : "Review"}</Button>
      </Flex>
    </Card>
  );
}

function GreenBatch({ items, now, onDone }: { items: ApprovalItem[]; now: Date | null; onDone: () => void }) {
  const { me } = useSession();
  const [sample] = useState(() => [...items].sort(() => Math.random() - 0.5).slice(0, 20));
  const [state, setState] = useState<Record<string, "released" | "refused">>({});
  const [running, setRunning] = useState(false);
  const done = Object.keys(state).length;

  async function releaseAll() {
    if (!me) return;
    setRunning(true);
    const queue = [...items];
    const worker = async () => {
      for (let a = queue.shift(); a; a = queue.shift()) {
        const id = a.proposal.proposal_id;
        try {
          const r = await api.decide(decision(a.proposal, me, nowIso(now)));
          setState((s) => ({ ...s, [id]: r.released ? "released" : "refused" }));
        } catch {
          setState((s) => ({ ...s, [id]: "refused" }));
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, items.length) }, worker));
    setRunning(false);
    onDone();
  }

  return (
    <Card size="3">
      <Flex justify="between" align="center" wrap="wrap" gap="3">
        <Text size="2">
          Sampled <Text weight="bold">{sample.length}</Text> of {items.length} for review. Check them, then release the batch.
        </Text>
        <Button size="3" loading={running} disabled={done === items.length} onClick={() => void releaseAll()}>
          Release batch of {items.length}
        </Button>
      </Flex>
      {(running || done > 0) && <Progress mt="4" value={(done / items.length) * 100} />}
      <Flex direction="column" gap="2" mt="4">
        {sample.map((a, i) => {
          const s = state[a.proposal.proposal_id];
          return (
            <motion.div key={a.proposal.proposal_id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0, transition: { delay: i * 0.03 } }}>
              <Flex justify="between" align="center" py="1" style={{ borderBottom: "1px solid var(--gray-a3)" }}>
                <Text size="2">
                  {ACTION_LABEL[a.proposal.action]} · <Link href={`/cases/${a.proposal.case_id}`}>{a.proposal.case_id}</Link>
                </Text>
                <AnimatePresence mode="wait">
                  {s && (
                    <motion.span key={s} initial={{ scale: 0 }} animate={{ scale: 1 }} transition={spring}>
                      <Badge color={s === "released" ? "grass" : "red"} variant="soft">{s}</Badge>
                    </motion.span>
                  )}
                </AnimatePresence>
              </Flex>
            </motion.div>
          );
        })}
      </Flex>
    </Card>
  );
}

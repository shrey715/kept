"use client";

import { Badge, Box, Button, Callout, Card, Dialog, Flex, Heading, Progress, Skeleton, Tabs, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { TierBadge } from "@/components/bits";
import { Rise, Stagger, spring } from "@/components/motion";
import { ReviewPanel } from "@/components/review-panel";
import { ACTION_LABEL, api, decision, money, when, type ApprovalItem } from "@/lib/api";
import { nowIso, useServerClock } from "@/lib/clock";
import { useSession } from "@/lib/session";

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

  if (!me) return null;
  return (
    <Stagger>
      <Rise>
        <Heading size="8">Approvals</Heading>
        <Text color="gray" size="2">Nothing reaches a customer until the right person releases it.</Text>
      </Rise>
      {error && (
        <Callout.Root color="red" mt="4">
          <Callout.Text>{error}</Callout.Text>
        </Callout.Root>
      )}
      {!items && !error && <Skeleton height="240px" mt="5" />}
      {items && items.length === 0 && (
        <Rise>
          <Card size="3" mt="5">
            <Flex direction="column" align="center" gap="2" py="6">
              <Text size="6" className="serif" weight="bold">Inbox zero</Text>
              <Text color="gray" size="2">Nothing is waiting for {me.title.toLowerCase()} approval.</Text>
            </Flex>
          </Card>
        </Rise>
      )}
      {stages.length > 0 && (
        <Rise>
          <Tabs.Root defaultValue={stages[0]} mt="5">
            <Tabs.List>
              {stages.map((s) => (
                <Tabs.Trigger key={s} value={s}>
                  {STAGES[s].label}
                  <Badge ml="2" radius="full" variant="soft">{byStage.get(s)!.length}</Badge>
                </Tabs.Trigger>
              ))}
            </Tabs.List>
            {stages.map((s) => (
              <Tabs.Content key={s} value={s}>
                <Text as="p" size="2" color="gray" my="4">{STAGES[s].blurb}</Text>
                {s === "green_batch" ? (
                  <GreenBatch items={byStage.get(s)!} now={now} onDone={load} />
                ) : (
                  <Flex direction="column" gap="3">
                    <AnimatePresence initial={false}>
                      {byStage.get(s)!.map((a, i) => (
                        <motion.div key={a.proposal.proposal_id} layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0, transition: { ...spring, delay: i * 0.05 } }} exit={{ opacity: 0, x: 40 }}>
                          <ApprovalRow item={a} onOpen={() => setOpen(a)} />
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </Flex>
                )}
              </Tabs.Content>
            ))}
          </Tabs.Root>
        </Rise>
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
    for (const a of items) {
      try {
        const r = await api.decide(decision(a.proposal, me, nowIso(now)));
        setState((s) => ({ ...s, [a.proposal.proposal_id]: r.released ? "released" : "refused" }));
      } catch {
        setState((s) => ({ ...s, [a.proposal.proposal_id]: "refused" }));
      }
    }
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

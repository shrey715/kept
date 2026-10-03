"use client";

import { MagnifyingGlassIcon } from "@radix-ui/react-icons";
import { Badge, Box, Callout, Card, Flex, Grid, Heading, Kbd, SegmentedControl, Skeleton, Table, Text, TextField } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { TierBadge } from "@/components/bits";
import { CountUp, Rise, Stagger } from "@/components/motion";
import { ACTION_LABEL, api, humanize, money, type QueueItem } from "@/lib/api";
import { useSession } from "@/lib/session";

type Filter = "all" | "red" | "amber" | "green" | "none";

export default function QueuePage() {
  const { me } = useSession();
  const router = useRouter();
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState(0);

  useEffect(() => {
    if (!me) return;
    let live = true;
    api.queue(me).then((q) => live && setItems(q), (e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [me]);

  const shown = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (items ?? []).filter(
      (i) =>
        (filter === "all" || (filter === "none" ? !i.tier : i.tier === filter)) &&
        (!s || i.case_id.toLowerCase().includes(s) || (i.display_name ?? "").toLowerCase().includes(s)),
    );
  }, [items, filter, search]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === "j") setCursor((c) => Math.min(c + 1, shown.length - 1));
      if (e.key === "k") setCursor((c) => Math.max(c - 1, 0));
      if (e.key === "Enter" && shown[cursor]) router.push(`/cases/${shown[cursor].case_id}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown, cursor, router]);

  const actionable = (items ?? []).filter((i) => i.action);
  const total = (items ?? []).reduce((s, i) => s + Number(i.total_overdue), 0);
  const ev = actionable.reduce((s, i) => s + Number(i.expected_value), 0);
  const review = (items ?? []).filter((i) => i.tier === "red").length;

  return (
    <Stagger>
      <Rise>
        <Flex justify="between" align="end" wrap="wrap" gap="3">
          <Box>
            <Heading size="8">Today&apos;s queue</Heading>
            <Text color="gray" size="2">
              Ranked by expected recovery: uplift over doing nothing, times the balance at risk.
            </Text>
          </Box>
          <Text size="1" color="gray">
            <Kbd>j</Kbd> <Kbd>k</Kbd> to move · <Kbd>Enter</Kbd> to open
          </Text>
        </Flex>
      </Rise>

      <Grid columns={{ initial: "2", md: "4" }} gap="3" mt="5">
        {[
          { label: "Open cases", value: items?.length ?? 0, fmt: (n: number) => Math.round(n).toString(), to: "all" as Filter },
          { label: "Balance at risk", value: total, fmt: (n: number) => money(n), to: "all" as Filter },
          { label: "Expected recovery", value: ev, fmt: (n: number) => money(n), to: "amber" as Filter },
          { label: "Need specialist review", value: review, fmt: (n: number) => Math.round(n).toString(), to: "red" as Filter },
        ].map((s) => (
          <Rise key={s.label}>
            <Card size="2" asChild style={{ cursor: "pointer", outline: filter === s.to && s.to !== "all" ? "2px solid var(--accent-8)" : undefined }}>
              <motion.button whileHover={{ y: -3 }} whileTap={{ scale: 0.98 }} onClick={() => { setFilter(s.to); setCursor(0); }} style={{ textAlign: "left", width: "100%" }}>
              <Text as="div" size="1" color="gray" weight="medium">
                {s.label}
              </Text>
              <Text as="div" size="7" weight="bold" className="serif" mt="1">
                {items ? <CountUp value={s.value} format={s.fmt} /> : <Skeleton>0000</Skeleton>}
              </Text>
              </motion.button>
            </Card>
          </Rise>
        ))}
      </Grid>

      <Rise>
        <Flex mt="5" gap="3" align="center" wrap="wrap">
          <SegmentedControl.Root value={filter} onValueChange={(v) => { setFilter(v as Filter); setCursor(0); }}>
            <SegmentedControl.Item value="all">All</SegmentedControl.Item>
            <SegmentedControl.Item value="red">Red</SegmentedControl.Item>
            <SegmentedControl.Item value="amber">Amber</SegmentedControl.Item>
            <SegmentedControl.Item value="green">Green</SegmentedControl.Item>
            <SegmentedControl.Item value="none">No action</SegmentedControl.Item>
          </SegmentedControl.Root>
          <TextField.Root placeholder="Search name or case" value={search} onChange={(e) => setSearch(e.target.value)} style={{ minWidth: 240 }}>
            <TextField.Slot>
              <MagnifyingGlassIcon />
            </TextField.Slot>
          </TextField.Root>
        </Flex>
      </Rise>

      {error && (
        <Callout.Root color="red" mt="4">
          <Callout.Text>Couldn&apos;t load the queue: {error}</Callout.Text>
        </Callout.Root>
      )}

      <Rise>
        <Card size="1" mt="4" style={{ padding: 0, overflow: "hidden" }}>
          <Table.Root variant="ghost">
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeaderCell>Customer</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Recommendation</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Tier</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell justify="end">Overdue</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell justify="end">Expected</Table.ColumnHeaderCell>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {!items &&
                [0, 1, 2, 3, 4].map((i) => (
                  <Table.Row key={i}>
                    {[0, 1, 2, 3, 4].map((j) => (
                      <Table.Cell key={j}>
                        <Skeleton>Loading the queue</Skeleton>
                      </Table.Cell>
                    ))}
                  </Table.Row>
                ))}
              <AnimatePresence initial={false}>
                {shown.map((i, n) => (
                  <motion.tr
                    key={i.case_id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(n, 12) * 0.035 } }}
                    exit={{ opacity: 0, x: -12 }}
                    className="rt-TableRow row-link"
                    data-active={n === cursor}
                    onClick={() => router.push(`/cases/${i.case_id}`)}
                    onMouseEnter={() => setCursor(n)}
                  >
                    <Table.Cell>
                      <Text as="div" weight="medium">
                        {i.display_name ?? i.golden_customer_id}
                      </Text>
                      <Text as="div" size="1" color="gray" className="tabular">
                        {i.case_id} · {i.max_dpd} days past due
                      </Text>
                    </Table.Cell>
                    <Table.Cell>
                      <Flex align="center" gap="2" wrap="wrap">
                        <Text>{i.action ? ACTION_LABEL[i.action] : "No action"}</Text>
                        {i.hardship && <Badge color="amber" variant="soft">hardship</Badge>}
                        {i.hard_stop && <Badge color="gray" variant="soft">hard stop</Badge>}
                        {i.proposal_status && i.proposal_status !== "pending" && (
                          <Badge color={i.proposal_status === "released" ? "grass" : "gray"} variant="outline">
                            {humanize(i.proposal_status)}
                          </Badge>
                        )}
                      </Flex>
                      <Text as="div" size="1" color="gray">
                        {i.action ? i.headline : i.no_action_reason}
                      </Text>
                    </Table.Cell>
                    <Table.Cell>{i.tier ? <TierBadge tier={i.tier} long={false} /> : <Text color="gray">—</Text>}</Table.Cell>
                    <Table.Cell justify="end" className="tabular">
                      {money(i.total_overdue, true)}
                    </Table.Cell>
                    <Table.Cell justify="end" className="tabular">
                      <Text weight="medium">{Number(i.expected_value) > 0 ? money(i.expected_value) : "—"}</Text>
                    </Table.Cell>
                  </motion.tr>
                ))}
              </AnimatePresence>
            </Table.Body>
          </Table.Root>
          {items && shown.length === 0 && (
            <Flex p="6" justify="center">
              <Text color="gray">No cases match.</Text>
            </Flex>
          )}
        </Card>
      </Rise>
    </Stagger>
  );
}

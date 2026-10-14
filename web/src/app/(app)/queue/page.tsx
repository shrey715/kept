"use client";

import { SectionTitle } from "@/components/page-header";
import { ArrowRightIcon, ArrowTopRightIcon, LayersIcon, MagnifyingGlassIcon, StarIcon, TargetIcon } from "@radix-ui/react-icons";
import { Avatar, Badge, Box, Callout, Flex, Grid, Kbd, Skeleton, Table, Text, TextField } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { MapleMark, TierBadge, initials, tierColor } from "@/components/bits";
import { CountUp, Rise, Stagger } from "@/components/motion";
import { NAV } from "@/components/shell";
import { ACTION_LABEL, api, humanize, money, type QueueItem } from "@/lib/api";
import { keys, load, peek, prefetch } from "@/lib/live";
import { useSession } from "@/lib/session";

type Filter = "all" | "red" | "amber" | "green" | "none";
const FILTERS: [Filter, string][] = [
  ["all", "All cases"],
  ["red", "Red"],
  ["amber", "Amber"],
  ["green", "Green"],
  ["none", "No action"],
];
const matches = (i: QueueItem, f: Filter) => f === "all" || (f === "none" ? !i.tier : i.tier === f);

export default function QueuePage() {
  const { me } = useSession();
  const router = useRouter();
  const [items, setItems] = useState<QueueItem[] | null>(() => (me ? (peek<QueueItem[]>(keys.queue(me.userId)) ?? null) : null));
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState(0);

  useEffect(() => {
    if (!me) return;
    let live = true;
    load(keys.queue(me.userId), () => api.queue(me), { fresh: 0 }).then(
      (q) => live && setItems(q),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [me]);

  const shown = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (items ?? []).filter(
      (i) => matches(i, filter) && (!s || i.case_id.toLowerCase().includes(s) || (i.display_name ?? "").toLowerCase().includes(s)),
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

  const all = items ?? [];
  const actionable = all.filter((i) => i.action);
  const total = all.reduce((s, i) => s + Number(i.total_overdue), 0);
  const ev = actionable.reduce((s, i) => s + Number(i.expected_value), 0);
  const review = all.filter((i) => i.tier === "red").length;
  const pick = (f: Filter) => {
    setFilter(f);
    setCursor(0);
  };
  // hovering a row warms its case page: the route, the card and the customer
  const warm = (caseId: string) => {
    if (!me) return;
    router.prefetch(`/cases/${caseId}`);
    prefetch(keys.card(caseId, me.userId), () => api.card(caseId, me));
    prefetch(keys.customer(caseId, me.userId), () => api.customer(caseId, me));
  };
  const links = NAV.filter((n) => n.href !== "/queue" && n.href !== "/demo" && me && n.show(me.role));

  return (
    <Stagger>
      <Rise>
        <Flex justify="between" align="end" wrap="wrap" gap="4">
          <h1 className="k-display">
            Today&apos;s
            <span className="k-inline-chip" aria-hidden>
              <LayersIcon />
            </span>
            queue,
            <br />
            ranked by
            <span className="k-inline-chip hi" aria-hidden>
              <StarIcon />
            </span>
            recovery
          </h1>
          <Text size="1" color="gray" mb="2" className="k-desktop-only">
            <Kbd>j</Kbd> <Kbd>k</Kbd> to move · <Kbd>Enter</Kbd> to open
          </Text>
        </Flex>
      </Rise>

      <Rise>
        <Flex mt="5" gap="2" align="center" wrap="wrap" justify="between">
          <div className="k-tabs" role="tablist" aria-label="Filter by tier">
            {FILTERS.map(([f, label]) => (
              <button key={f} role="tab" aria-selected={filter === f} className="k-tab" data-active={filter === f} onClick={() => pick(f)}>
                {label}
                {items && <span className="count">{all.filter((i) => matches(i, f)).length}</span>}
              </button>
            ))}
          </div>
          <TextField.Root size="3" placeholder="Search name or case" value={search} onChange={(e) => setSearch(e.target.value)} style={{ minWidth: 260, background: "var(--k-chip)" }}>
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

      <Grid columns={{ initial: "1", lg: "minmax(0, 1fr) 300px" }} gap="3" mt="3">
        <Flex direction="column" gap="3" style={{ minWidth: 0 }}>
          <Grid columns={{ initial: "1", sm: "2", md: "3" }} gap="3">
            <Rise>
              <StatCard
                icon={<TargetIcon />}
                title="With an action today"
                big={items ? <CountUp value={actionable.length} format={(n) => Math.round(n).toString()} /> : <Skeleton>000</Skeleton>}
                of={items ? `/ ${all.length} open` : ""}
                share={all.length ? actionable.length / all.length : 0}
              />
            </Rise>
            <Rise>
              <StatCard
                hi
                icon={<StarIcon />}
                title="Expected recovery"
                big={items ? <CountUp value={ev} format={(n) => money(n)} /> : <Skeleton>$0,000</Skeleton>}
                of={items ? `/ ${money(total)} at risk` : ""}
                share={total ? ev / total : 0}
              />
            </Rise>
            <Rise>
              <div className="k-card dark" style={{ height: "100%", minHeight: 196, display: "flex", flexDirection: "column" }}>
                <div aria-hidden style={{ position: "absolute", right: -40, top: -30, opacity: 0.9, filter: "drop-shadow(0 0 40px rgba(229,41,63,.55))" }}>
                  <MapleMark size={190} />
                </div>
                <div aria-hidden style={{ position: "absolute", inset: 0, background: "linear-gradient(100deg, #1c1917 38%, rgba(28,25,23,.55) 70%, rgba(28,25,23,.1))" }} />
                <Box style={{ position: "relative", maxWidth: 220 }}>
                  <Text as="div" size="6" style={{ letterSpacing: "-0.03em", lineHeight: 1.1 }}>
                    {items ? review : "–"} need a specialist and a second person
                  </Text>
                </Box>
                <Box mt="auto" pt="4" style={{ position: "relative" }}>
                  <button
                    className="k-strong-btn"
                    onClick={() => pick("red")}
                    style={{ width: "100%", justifyContent: "center", background: "#faf7f2", color: "#1c1917" }}
                  >
                    Show Red cases <ArrowRightIcon />
                  </button>
                </Box>
              </div>
            </Rise>
          </Grid>

          <Rise>
            <div className="k-card" style={{ padding: 22 }}>
              <Flex align="center" gap="3" wrap="wrap">
                <SectionTitle eyebrow="Portfolio" title="Cases by days past due" icon={<LayersIcon />} mb="0" />
                <Flex gap="4" ml={{ initial: "0", sm: "4" }} align="center">
                  <Legend color="var(--k-strong)" label="Open cases" />
                  <Legend color="var(--k-red)" label="With an action" />
                </Flex>
                <span className="k-badge" style={{ marginLeft: "auto", height: 34, padding: "0 12px", borderRadius: 12 }}>
                  {all.length} cases
                </span>
              </Flex>
              <DpdChart items={all} />
            </div>
          </Rise>

          <Rise>
            <div className="k-card" style={{ padding: 0, overflow: "hidden" }}>
              <Flex align="center" gap="3" px="5" pt="4" pb="2">
                <SectionTitle eyebrow="Worklist" title="Cases" mb="0" />
                <span className="k-badge">{shown.length}</span>
              </Flex>
              <Table.Root variant="ghost">
                <Table.Header>
                  <Table.Row>
                    <Table.ColumnHeaderCell pl="5">Customer</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell>Recommendation</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell>Tier</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell justify="end">Overdue</Table.ColumnHeaderCell>
                    <Table.ColumnHeaderCell justify="end" pr="5">
                      Expected
                    </Table.ColumnHeaderCell>
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
                        onMouseEnter={() => {
                          setCursor(n);
                          warm(i.case_id);
                        }}
                      >
                        <Table.Cell pl="5">
                          <Flex align="center" gap="3">
                            <Avatar
                              size="2"
                              radius="full"
                              variant="soft"
                              color={i.tier ? tierColor(i.tier) : "gray"}
                              fallback={initials(i.display_name ?? i.golden_customer_id)}
                            />
                            <Box>
                              <Text as="div" weight="medium">
                                {i.display_name ?? i.golden_customer_id}
                              </Text>
                              <Text as="div" size="1" color="gray" className="tabular" style={{ whiteSpace: "nowrap" }}>
                                {i.case_id} · {i.max_dpd} days past due
                              </Text>
                            </Box>
                          </Flex>
                        </Table.Cell>
                        <Table.Cell>
                          <Flex align="center" gap="2" wrap="wrap">
                            <Text>{i.action ? ACTION_LABEL[i.action] : "No action"}</Text>
                            {i.hardship && (
                              <Badge color="amber" variant="soft">
                                hardship
                              </Badge>
                            )}
                            {i.hard_stop && (
                              <Badge color="gray" variant="soft">
                                hard stop
                              </Badge>
                            )}
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
                        <Table.Cell justify="end" className="tabular" pr="5">
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
            </div>
          </Rise>
        </Flex>

        {/* the rest of the workspace, one card each */}
        <Flex direction="column" gap="3">
          <Grid columns="2" gap="3">
            {links.slice(0, 2).map((n) => (
              <Rise key={n.href}>
                <Link href={n.href} className="k-card k-link" style={{ display: "grid", placeItems: "center", gap: 10, minHeight: 112, textAlign: "center" }}>
                  <span className="k-chip">
                    <n.icon />
                  </span>
                  <Text size="2" weight="medium">
                    {n.label}
                  </Text>
                </Link>
              </Rise>
            ))}
          </Grid>
          {[...links.slice(2), NAV.find((n) => n.href === "/demo")!].map((n) => (
            <Rise key={n.href}>
              <Link href={n.href} className="k-card k-link">
                <Flex justify="between" align="start">
                  <span className="k-chip">
                    <n.icon />
                  </span>
                  <ArrowTopRightIcon className="arrow" width={18} height={18} />
                </Flex>
                <Text as="div" size="3" weight="medium" mt="3">
                  {n.label}
                </Text>
                <Text as="div" size="1" color="gray" mt="1">
                  {n.blurb}
                </Text>
              </Link>
            </Rise>
          ))}
        </Flex>
      </Grid>
    </Stagger>
  );
}

function StatCard({ icon, title, big, of, share, hi = false }: { icon: React.ReactNode; title: string; big: React.ReactNode; of: string; share: number; hi?: boolean }) {
  const pct = Math.round(share * 100);
  return (
    <div className={`k-card${hi ? " hi" : ""}`} style={{ height: "100%", minHeight: 196 }}>
      <Flex align="center" gap="3">
        <span className="k-chip" style={hi ? { background: "var(--k-hi-chip)", color: "var(--k-hi-ink)" } : undefined}>
          {icon}
        </span>
        <Text size="2" weight="medium">
          {title}
        </Text>
      </Flex>
      <Flex align="baseline" gap="2" mt="4" wrap="wrap">
        <span className="k-big">{big}</span>
        <Text size="2" style={{ opacity: 0.6 }}>
          {of}
        </Text>
        <span className="k-badge" style={{ alignSelf: "start" }}>
          {pct}%
        </span>
      </Flex>
      <div className="k-segs" style={{ marginTop: 16 }} aria-hidden>
        {Array.from({ length: 8 }, (_, k) => (
          <i key={k} className={k < Math.round(share * 8) || (k === 0 && share > 0) ? "on" : ""} />
        ))}
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <Flex align="center" gap="2">
      <span style={{ width: 8, height: 8, borderRadius: 99, background: color }} />
      <Text size="1" color="gray">
        {label}
      </Text>
    </Flex>
  );
}

/** Open cases in 15-day bands of days past due: a capsule per band, the red part the share with an action. */
function DpdChart({ items }: { items: QueueItem[] }) {
  const bands = Array.from({ length: 8 }, (_, k) => {
    const inBand = items.filter((i) => (k === 7 ? i.max_dpd >= 105 : i.max_dpd >= k * 15 && i.max_dpd < (k + 1) * 15));
    return { label: k === 7 ? "105+" : `${k * 15}–${k * 15 + 14}`, n: inBand.length, acted: inBand.filter((i) => i.action).length };
  });
  const max = Math.max(1, ...bands.map((b) => b.n));
  const top = bands.findIndex((b) => b.n === max);
  return (
    <Box mt="4">
      <div className="k-capsules">
        {bands.map((b, k) => {
          const h = b.n ? 18 + (b.n / max) * 82 : 62;
          const part = b.n ? Math.max(b.acted ? 18 : 0, (b.acted / b.n) * 100) : 0;
          return (
            <motion.div
              key={b.label}
              className={`k-capsule${b.n ? "" : " empty"}`}
              initial={{ height: 0 }}
              animate={{ height: `${h}%` }}
              transition={{ type: "spring", stiffness: 160, damping: 22, delay: 0.1 + k * 0.05 }}
              title={`${b.label} days: ${b.n} cases, ${b.acted} with an action`}
            >
              {b.n > 0 && <span className="dot" style={{ top: 10 }} />}
              {part > 0 && (
                <span className="part" style={{ height: `${part}%` }}>
                  <span className="dot" style={{ top: 10 }} />
                </span>
              )}
              {k === top && b.n > 0 && (
                <span className="tag k-badge" style={{ top: 4, background: "var(--k-strong)", color: "var(--k-on-strong)" }}>
                  {b.n}
                </span>
              )}
              {k === top && b.acted > 0 && (
                <span className="tag k-badge" style={{ bottom: `calc(${part}% - 30px)`, background: "var(--k-hi)", color: "var(--k-hi-ink)" }}>
                  {Math.round((b.acted / b.n) * 100)}%
                </span>
              )}
            </motion.div>
          );
        })}
      </div>
      <div style={{ display: "grid", gridAutoFlow: "column", gridAutoColumns: "minmax(0, 1fr)", marginTop: 10 }}>
        {bands.map((b, k) => (
          <Text key={b.label} size="1" align="center" color="gray" weight={k === top ? "bold" : "regular"} className="tabular">
            {b.label}
          </Text>
        ))}
      </div>
      <Text as="div" size="1" color="gray" align="center" mt="1">
        days past due
      </Text>
    </Box>
  );
}

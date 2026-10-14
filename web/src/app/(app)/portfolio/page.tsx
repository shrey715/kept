"use client";

import {
  ArrowTopRightIcon,
  CodeIcon,
  DashboardIcon,
  DownloadIcon,
  ExclamationTriangleIcon,
  InfoCircledIcon,
  LightningBoltIcon,
  MagnifyingGlassIcon,
  StarIcon,
  TargetIcon,
} from "@radix-ui/react-icons";
import { Box, Callout, Flex, Grid, Select, Skeleton, Table, Text, TextField } from "@radix-ui/themes";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { TierBadge, initials, tierTint } from "@/components/bits";
import { CountUp, Donut, Rise, Stagger } from "@/components/motion";
import { BriefCard } from "@/components/brief-card";
import { ModelPanels } from "@/components/model-panels";
import { PageHeader, SectionTitle, TablePanel } from "@/components/page-header";
import { SqlBlock } from "@/components/sql-block";
import { download, toCsv } from "@/lib/csv";
import { ACTION_LABEL, api, money, type Action, type Governance, type Portfolio, type PortfolioPage, type Tier } from "@/lib/api";
import { keys, load, peek } from "@/lib/live";
import { can, useSession } from "@/lib/session";

const BUCKETS = ["current", "1-30", "31-60", "61-90", "91-120", "121+"];
const PAGE = 50;
const TONE = {
  good: { icon: <StarIcon />, tint: "mint" },
  warn: { icon: <ExclamationTriangleIcon />, tint: "rose" },
  info: { icon: <InfoCircledIcon />, tint: "ice" },
} as const;

export default function PortfolioPage() {
  const { me } = useSession();
  const [p, setP] = useState<Portfolio | null>(() => (me ? (peek<Portfolio>(keys.portfolio(me.userId)) ?? null) : null));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    let live = true;
    load(keys.portfolio(me.userId), () => api.portfolio(me), { fresh: 0 }).then(
      (x) => live && setP(x),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [me]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const loadBrief = useCallback(() => api.portfolioBrief(me!), [me?.userId]);
  if (!me) return null;
  const share = (n: number, d: number) => (d ? n / d : 0);
  return (
    <Stagger>
      <Rise>
        <PageHeader
          icon={<DashboardIcon />}
          eyebrow="Portfolio"
          title="Portfolio overview"
          sub={
            <>
              Open cases, balances and recommended actions from the latest nightly run, with the query behind each figure.
              {p?.as_of && <> Features as of {new Date(p.as_of).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}</>}
            </>
          }
        />
      </Rise>
      {error && (
        <Callout.Root color="red" mb="4">
          <Callout.Text>Couldn&apos;t load the portfolio: {error}</Callout.Text>
        </Callout.Root>
      )}

      <Grid columns={{ initial: "2", md: "5" }} gap="3">
        {[
          { label: "Open cases", v: p?.cases, f: (n: number) => Math.round(n).toLocaleString("en-CA"), icon: <DashboardIcon />, tint: "ice" },
          { label: "Balance at risk", v: p?.balance, f: (n: number) => money(n), icon: <TargetIcon />, tint: "butter" },
          { label: "Expected recovery", v: p?.expected, f: (n: number) => money(n), icon: <StarIcon />, hi: true },
          { label: "With an action", v: p ? share(p.actionable, p.cases) * 100 : undefined, f: (n: number) => `${Math.round(n)}%`, icon: <LightningBoltIcon />, tint: "mint" },
          { label: "Specialist review", v: p?.red, f: (n: number) => Math.round(n).toLocaleString("en-CA"), icon: <ExclamationTriangleIcon />, tint: "rose" },
        ].map((k) => (
          <Rise key={k.label}>
            <div className={`k-card${k.hi ? " hi" : ""}${k.tint ? ` t-${k.tint}` : ""}`} style={{ height: "100%" }}>
              <Flex align="center" gap="2">
                <span className="k-chip" style={{ width: 32, height: 32, borderRadius: 10, ...(k.hi ? { background: "var(--k-hi-chip)", color: "var(--k-hi-ink)" } : {}) }}>
                  {k.icon}
                </span>
                <Text size="1" weight="medium">
                  {k.label}
                </Text>
              </Flex>
              <div className="k-big" style={{ fontSize: "clamp(22px, 5.6vw, 34px)", marginTop: 14, whiteSpace: "nowrap" }}>
                {k.v === undefined ? <Skeleton>000,000</Skeleton> : <CountUp value={k.v} format={k.f} />}
              </div>
            </div>
          </Rise>
        ))}
      </Grid>

      {p && (
        <Box mt="5">
          <BriefCard load={loadBrief} eyebrow="Summary" title="Key points for today" />
        </Box>
      )}
      {p && p.insights.length > 0 && (
        <Box mt="5">
          <SectionTitle eyebrow="Insights" title="Portfolio insights" />
          <Grid columns={{ initial: "1", md: "2" }} gap="3">
            {p.insights.map((i) => (
              <Rise key={i.id}>
                <InsightCard i={i} />
              </Rise>
            ))}
          </Grid>
        </Box>
      )}

      {p ? (
        <Grid columns={{ initial: "1", lg: "2" }} gap="3" mt="5">
          <Rise>
            <div className="k-card" style={{ padding: 22, height: "100%" }}>
              <SectionTitle eyebrow="Balances" title="Balance by days past due" />
              <Grid columns="2" gap="4">
                <Bars title="Balance at risk" rows={order(p.by_bucket).map((s) => ({ key: s.key, v: s.balance, n: s.cases }))} fmt={(v) => money(v)} color="var(--k-strong)" />
                <Bars title="Expected recovery" rows={order(p.by_bucket).map((s) => ({ key: s.key, v: s.expected, n: s.cases }))} fmt={(v) => money(v)} color="var(--k-red)" />
              </Grid>
              <Text as="p" size="1" color="gray" mt="3">
                Two charts, one scale each. Expected recovery is uplift over waiting times the balance.
              </Text>
            </div>
          </Rise>
          <Rise>
            <div className="k-card" style={{ padding: 22, height: "100%" }}>
              <SectionTitle eyebrow="Recommendations" title="Cases by recommended action" />
              <Bars
                title="Open cases"
                rows={p.by_action.map((s) => ({ key: s.key === "none" ? "No action" : (ACTION_LABEL[s.key as Action] ?? s.key), v: s.cases, n: s.cases }))}
                fmt={(v) => Math.round(v).toLocaleString("en-CA")}
                color="var(--k-strong)"
                sortByValue
              />
            </div>
          </Rise>
          <Rise>
            <div className="k-card" style={{ padding: 22, height: "100%" }}>
              <SectionTitle eyebrow="Strategy test" title="Promise-kept rate by strategy" />
              <Forest cells={p.ab_test} />
            </div>
          </Rise>
          <Rise>
            <div className="k-card" style={{ padding: 22, height: "100%" }}>
              <SectionTitle eyebrow="Cohorts" title="Promise-kept rate by quarter opened" />
              <Heatmap cells={p.cohorts} />
            </div>
          </Rise>
        </Grid>
      ) : (
        !error && (
          <Grid columns={{ initial: "1", lg: "2" }} gap="3" mt="5">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} height="300px" style={{ borderRadius: 24 }} />
            ))}
          </Grid>
        )
      )}

      <ModelsSection />

      {can.portfolioCases(me.role) ? (
        <CaseExplorer />
      ) : (
        <Text as="p" size="2" color="gray" mt="5">
          Analysts see aggregates only: single cases stay with specialists, team leads and compliance.
        </Text>
      )}
    </Stagger>
  );
}

const order = <T extends { key: string }>(xs: T[]) => [...xs].sort((a, b) => BUCKETS.indexOf(a.key) - BUCKETS.indexOf(b.key));

function InsightCard({ i }: { i: Portfolio["insights"][number] }) {
  const [sql, setSql] = useState(false);
  const t = TONE[i.tone];
  return (
    <div className="k-card" style={{ height: "100%" }}>
      <Flex gap="3" align="start">
        <span className={`k-chip round t-${t.tint}`}>{t.icon}</span>
        <Box style={{ minWidth: 0, flex: 1 }}>
          <Text as="div" size="3" weight="medium" style={{ letterSpacing: "-0.01em" }}>
            {i.title}
          </Text>
          <Text as="p" size="2" color="gray" mt="1">
            {i.body}
          </Text>
          <button className="k-text-btn" style={{ marginTop: 8, marginLeft: -8 }} onClick={() => setSql((s) => !s)} aria-expanded={sql}>
            <CodeIcon style={{ verticalAlign: -2, marginRight: 4 }} />
            {sql ? "Hide the SQL" : "Show the SQL"}
          </button>
          <AnimatePresence initial={false}>
            {sql && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} style={{ overflow: "hidden" }}>
                <SqlBlock sql={i.sql} />
              </motion.div>
            )}
          </AnimatePresence>
        </Box>
      </Flex>
    </div>
  );
}

/** Horizontal bars, one series, one scale; the value sits at the end of each bar and a hover shows the case count. */
function Bars({ title, rows, fmt, color, sortByValue = false }: { title: string; rows: { key: string; v: number; n: number }[]; fmt: (v: number) => string; color: string; sortByValue?: boolean }) {
  const rs = sortByValue ? [...rows].sort((a, b) => b.v - a.v) : rows;
  const max = Math.max(...rs.map((r) => r.v), 1);
  const [hover, setHover] = useState<string | null>(null);
  return (
    <Box>
      <Text as="div" size="1" color="gray" mb="2">
        {title}
      </Text>
      <Flex direction="column" gap="2">
        {rs.map((r, i) => (
          <Box key={r.key} onMouseEnter={() => setHover(r.key)} onMouseLeave={() => setHover(null)} title={`${r.key}: ${fmt(r.v)} · ${r.n.toLocaleString("en-CA")} cases`}>
            <Flex justify="between" gap="2">
              <Text size="1" truncate>
                {r.key}
              </Text>
              <Text size="1" className="tabular" weight={hover === r.key ? "bold" : "regular"}>
                {fmt(r.v)}
                {hover === r.key && <Text color="gray"> · {r.n.toLocaleString("en-CA")} cases</Text>}
              </Text>
            </Flex>
            <div className="k-act-track" style={{ height: 8, marginTop: 4 }}>
              <motion.span
                className="k-act-bar"
                style={{ background: color, opacity: hover && hover !== r.key ? 0.45 : 1 }}
                initial={{ width: 0 }}
                animate={{ width: `${(r.v / max) * 100}%` }}
                transition={{ type: "spring", stiffness: 140, damping: 22, delay: i * 0.04 }}
              />
            </div>
          </Box>
        ))}
      </Flex>
    </Box>
  );
}

/** A forest plot: each strategy's kept rate (dot) and its Wilson 95% interval (whisker), on one shared scale. */
function Forest({ cells }: { cells: Portfolio["ab_test"] }) {
  if (!cells.length) return <Text color="gray">No closed randomised cases.</Text>;
  const lo = Math.min(...cells.map((c) => c.kept_lo)) - 0.01;
  const hi = Math.max(...cells.map((c) => c.kept_hi)) + 0.01;
  const x = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const champ = cells.find((c) => c.test_cell === "champion");
  return (
    <Box>
      <Flex direction="column" gap="3">
        {cells.map((c, i) => (
          <Box key={c.test_cell} title={`${c.test_cell}: ${(c.kept_rate * 100).toFixed(1)}% (95% CI ${(c.kept_lo * 100).toFixed(1)}–${(c.kept_hi * 100).toFixed(1)}), ${c.promises.toLocaleString("en-CA")} promises`}>
            <Flex justify="between" mb="1">
              <Text size="2" weight={c.test_cell === "champion" ? "bold" : "regular"}>
                {c.test_cell.replace(/_/g, " ")}
              </Text>
              <Text size="1" color="gray" className="tabular">
                {(c.kept_rate * 100).toFixed(1)}% · {(c.kept_lo * 100).toFixed(1)}–{(c.kept_hi * 100).toFixed(1)} · n={c.promises.toLocaleString("en-CA")}
              </Text>
            </Flex>
            <div className="k-forest">
              {champ && <span className="k-forest-ref" style={{ left: x(champ.kept_rate) }} />}
              <motion.span
                className="k-forest-ci"
                initial={{ opacity: 0, scaleX: 0 }}
                animate={{ opacity: 1, scaleX: 1 }}
                transition={{ delay: 0.1 + i * 0.06 }}
                style={{ left: x(c.kept_lo), width: `calc(${x(c.kept_hi)} - ${x(c.kept_lo)})` }}
              />
              <motion.span
                className="k-forest-dot"
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: "spring", stiffness: 400, damping: 20, delay: 0.2 + i * 0.06 }}
                style={{ left: x(c.kept_rate), background: c.test_cell === "champion" ? "var(--k-strong)" : "var(--k-red)" }}
              />
            </div>
          </Box>
        ))}
      </Flex>
      <Flex justify="between" mt="2">
        <Text size="1" color="gray" className="tabular">
          {(lo * 100).toFixed(0)}%
        </Text>
        <Text size="1" color="gray">
          dot = kept rate · bar = 95% interval · line = champion
        </Text>
        <Text size="1" color="gray" className="tabular">
          {(hi * 100).toFixed(0)}%
        </Text>
      </Flex>
    </Box>
  );
}

/** Quarters by product, one sequential maple scale (light to dark); cells under 30 promises are left blank. */
function Heatmap({ cells }: { cells: Portfolio["cohorts"] }) {
  const quarters = [...new Set(cells.map((c) => c.quarter))].sort();
  const products = [...new Set(cells.map((c) => c.product))].sort();
  const rates = cells.map((c) => c.kept_rate).filter((r): r is number => r != null);
  const [min, max] = [Math.min(...rates), Math.max(...rates)];
  const at = new Map(cells.map((c) => [`${c.quarter}|${c.product}`, c]));
  if (!rates.length) return <Text color="gray">Not enough promises yet.</Text>;
  return (
    <Box style={{ overflowX: "auto" }}>
      <div className="k-heat" style={{ gridTemplateColumns: `72px repeat(${products.length}, minmax(64px, 1fr))` }}>
        <span />
        {products.map((p) => (
          <Text key={p} size="1" color="gray" align="center" truncate>
            {p.replace(/_/g, " ")}
          </Text>
        ))}
        {quarters.map((q) => (
          <QuarterRow key={q} q={q} products={products} at={at} min={min} max={max} />
        ))}
      </div>
      <Flex align="center" gap="2" mt="3">
        <Text size="1" color="gray" className="tabular">
          {(min * 100).toFixed(0)}%
        </Text>
        <span className="k-heat-scale" />
        <Text size="1" color="gray" className="tabular">
          {(max * 100).toFixed(0)}%
        </Text>
        <Text size="1" color="gray" ml="3">
          blank: under 30 promises
        </Text>
      </Flex>
      <Text as="p" size="1" color="gray" mt="2">
        Kept of kept plus broken. The latest quarters are still maturing: their open promises aren&apos;t counted yet, so read them as early, not worse.
      </Text>
    </Box>
  );
}

function QuarterRow({ q, products, at, min, max }: { q: string; products: string[]; at: Map<string, Portfolio["cohorts"][number]>; min: number; max: number }) {
  return (
    <>
      <Text size="1" color="gray" className="tabular" style={{ alignSelf: "center" }}>
        {q}
      </Text>
      {products.map((p) => {
        const c = at.get(`${q}|${p}`);
        const r = c?.kept_rate;
        const t = r == null ? 0 : (r - min) / (max - min || 1);
        return (
          <span
            key={p}
            className="k-heat-cell"
            data-empty={r == null}
            title={c ? `${q} · ${p}: ${r == null ? "too few" : `${(r * 100).toFixed(1)}%`} of ${c.promises} promises kept` : `${q} · ${p}: none`}
            style={r == null ? undefined : { background: `color-mix(in oklab, var(--k-red) ${Math.round(12 + t * 80)}%, var(--k-chip))`, color: t > 0.55 ? "#fff" : "var(--gray-12)" }}
          >
            {r == null ? "" : `${Math.round(r * 100)}`}
          </span>
        );
      })}
    </>
  );
}

/** The models behind the cards, how well they hold up, and the fairness and drift checks (the reports' JSON). */
function ModelsSection() {
  const { me } = useSession();
  const [g, setG] = useState<Governance | null>(null);
  useEffect(() => {
    if (!me) return;
    let live = true;
    api.portfolioModels(me).then((x) => live && setG(x), () => undefined);
    return () => {
      live = false;
    };
  }, [me]);
  if (!g) return null;
  return (
    <Box mt="6">
      <SectionTitle eyebrow="Models and governance" title="Model performance and monitoring" />
      <ModelPanels g={g} />
    </Box>
  );
}

/** Tonight's cards, filtered and sorted on the server, a page at a time; the page can leave as CSV. */
function CaseExplorer() {
  const { me } = useSession();
  const [tier, setTier] = useState<string>("all");
  const [bucket, setBucket] = useState<string>("all");
  const [sort, setSort] = useState<string>("expected_value");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<PortfolioPage | null>(null);
  const filters = useMemo(() => {
    const f: Record<string, string> = { offset: String(offset), limit: String(PAGE), sort };
    if (tier !== "all") f.tier = tier;
    if (bucket !== "all") f.bucket = bucket;
    if (q.trim()) f.q = q.trim();
    return f;
  }, [tier, bucket, sort, q, offset]);

  useEffect(() => {
    if (!me) return;
    let live = true;
    const t = setTimeout(() => api.portfolioCases(me, filters).then((x) => live && setPage(x), () => live && setPage({ rows: [], total: 0 })), q ? 250 : 0); // debounce typing
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [me, filters, q]);

  const reset = (fn: () => void) => {
    fn();
    setOffset(0);
  };
  function exportCsv() {
    if (!page) return;
    const cols = ["case_id", "display_name", "current_bucket", "max_dpd", "total_overdue", "action", "tier", "p_paid_14d", "expected_value", "hardship", "hard_stop"];
    download(`kept-portfolio-${offset / PAGE + 1}.csv`, toCsv(page.rows as unknown as Record<string, unknown>[], cols));
  }

  return (
    <Box mt="5">
      <TablePanel
        title="All cases"
        aside={page && <span className="k-badge">{page.total.toLocaleString("en-CA")}</span>}
        sum={
          page && page.rows.length > 0 ? (
            <>
              Expected on this page <b>{money(page.rows.reduce((s, r) => s + Number(r.expected_value), 0))}</b>
            </>
          ) : undefined
        }
      >
        <Flex align="center" gap="3" wrap="wrap" px="4" pb="3">
          <Flex gap="2" wrap="wrap" align="center">
            <div className="k-tabs">
              {["all", "red", "amber", "green", "none"].map((t) => (
                <button key={t} className="k-tab" data-active={tier === t} style={{ height: 34 }} onClick={() => reset(() => setTier(t))}>
                  {t === "none" ? "No action" : t === "all" ? "All" : t[0].toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
            <Select.Root value={bucket} onValueChange={(v) => reset(() => setBucket(v))}>
              <Select.Trigger placeholder="Bucket" />
              <Select.Content>
                <Select.Item value="all">Every bucket</Select.Item>
                {BUCKETS.map((b) => (
                  <Select.Item key={b} value={b}>
                    {b}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
            <Select.Root value={sort} onValueChange={(v) => reset(() => setSort(v))}>
              <Select.Trigger />
              <Select.Content>
                <Select.Item value="expected_value">Expected recovery</Select.Item>
                <Select.Item value="total_overdue">Overdue</Select.Item>
                <Select.Item value="max_dpd">Days past due</Select.Item>
                <Select.Item value="p_paid_14d">Chance of payment</Select.Item>
              </Select.Content>
            </Select.Root>
            <TextField.Root placeholder="Name or case" value={q} onChange={(e) => reset(() => setQ(e.target.value))} style={{ width: 180 }}>
              <TextField.Slot>
                <MagnifyingGlassIcon />
              </TextField.Slot>
            </TextField.Root>
            <button className="k-round-btn" style={{ width: 36, height: 36 }} onClick={exportCsv} aria-label="Download this page as CSV" title="Download this page as CSV">
              <DownloadIcon />
            </button>
          </Flex>
        </Flex>
        <Box style={{ overflowX: "auto" }}>
          <Table.Root variant="ghost" size="1">
            <Table.Header>
              <Table.Row>
                <Table.ColumnHeaderCell pl="5">Case</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Bucket</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Recommendation</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell>Tier</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell justify="end">Overdue</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell justify="end">Paid in 14d</Table.ColumnHeaderCell>
                <Table.ColumnHeaderCell justify="end" pr="5">
                  Expected
                </Table.ColumnHeaderCell>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {!page &&
                [0, 1, 2, 3, 4, 5].map((i) => (
                  <Table.Row key={i}>
                    <Table.Cell colSpan={7}>
                      <Skeleton>Loading the cases</Skeleton>
                    </Table.Cell>
                  </Table.Row>
                ))}
              {page?.rows.map((r) => (
                <Table.Row key={r.case_id} className="row-link">
                  <Table.Cell pl="5">
                    <Link href={`/cases/${r.case_id}`} style={{ color: "inherit", textDecoration: "none", display: "flex", alignItems: "center", gap: 12 }}>
                      <span className={`k-ava${r.tier ? ` t-${tierTint(r.tier as Tier)}` : ""}`} aria-hidden>
                        {initials(r.display_name ?? r.case_id)}
                      </span>
                      <span>
                        <Text as="div" weight="medium">
                          {r.display_name ?? r.case_id}
                        </Text>
                        <Text as="div" size="1" color="gray" className="tabular">
                          {r.case_id} · {r.max_dpd} dpd {r.hardship ? "· hardship" : ""}
                          {r.hard_stop ? " · hard stop" : ""}
                        </Text>
                      </span>
                    </Link>
                  </Table.Cell>
                  <Table.Cell className="tabular">{r.current_bucket ?? "—"}</Table.Cell>
                  <Table.Cell>{r.action ? ACTION_LABEL[r.action as Action] : <Text color="gray">No action</Text>}</Table.Cell>
                  <Table.Cell>{r.tier ? <TierBadge tier={r.tier as Tier} long={false} /> : <Text color="gray">—</Text>}</Table.Cell>
                  <Table.Cell justify="end" className="tabular">
                    {money(r.total_overdue, true)}
                  </Table.Cell>
                  <Table.Cell justify="end" className="tabular">
                    {r.p_paid_14d == null ? (
                      "—"
                    ) : (
                      <Flex align="center" justify="end" gap="2" className={r.tier ? `t-${tierTint(r.tier as Tier)}` : undefined}>
                        {Math.round(r.p_paid_14d * 100)}%
                        <Donut value={r.p_paid_14d} size={22} />
                      </Flex>
                    )}
                  </Table.Cell>
                  <Table.Cell justify="end" className="tabular" pr="5">
                    {r.expected_value > 0 ? money(r.expected_value) : "—"}
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table.Root>
        </Box>
        {page && (
          <Flex align="center" justify="between" px="5" py="3">
            <Text size="1" color="gray" className="tabular">
              {page.total ? `${offset + 1}–${Math.min(offset + PAGE, page.total)} of ${page.total.toLocaleString("en-CA")}` : "No cases match."}
            </Text>
            <Flex gap="2">
              <button className="k-tab" style={{ height: 32 }} disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>
                Previous
              </button>
              <button className="k-tab" style={{ height: 32 }} disabled={offset + PAGE >= page.total} onClick={() => setOffset((o) => o + PAGE)}>
                Next <ArrowTopRightIcon style={{ transform: "rotate(45deg)" }} />
              </button>
            </Flex>
          </Flex>
        )}
      </TablePanel>
    </Box>
  );
}

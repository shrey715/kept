"use client";

import { Box, Flex, Grid, Text, VisuallyHidden } from "@radix-ui/themes";
import { motion, useInView, useReducedMotion } from "motion/react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { fmt } from "@/components/answer-chart";
import { SectionTitle } from "@/components/page-header";
import { api, type MoneyFlow, type Portfolio } from "@/lib/api";
import { useSession } from "@/lib/session";

type SNode = { id: string; label: string; col: number; color: string };
type SLink = { source: string; target: string; value: number; note: string };

const NODE_W = 12;
const PAD = 12;
const LABEL_W = 210; // room for the last column's labels
const LINE = 15; // minimum gap between two labels in one column
const count = (n: number) => Math.round(n).toLocaleString("en-CA");
const dollars = (n: number) => fmt(n, "money", true);

/** Width of an element, followed as it resizes. */
function useWidth<T extends HTMLElement>(fallback: number) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** A Sankey in plain SVG: columns of nodes stacked from the top, bands as filled curves sized by value.
 *  Bands grow in left to right when the chart comes into view; changing the links animates them. */
function Sankey({ nodes, links, height, unit, label }: { nodes: SNode[]; links: SLink[]; height: number; unit: (n: number) => string; label: string }) {
  const [wrap, measured] = useWidth<HTMLDivElement>(900);
  const W = Math.max(measured, 560); // narrower screens scale the drawing down instead of crowding it
  const H = height;
  const still = useReducedMotion() ?? false;
  const inView = useInView(wrap, { once: true });
  const clip = useId();
  const [hover, setHover] = useState<string | null>(null);

  const layout = useMemo(() => {
    const value = new Map<string, number>();
    const into = new Map<string, number>();
    const out = new Map<string, number>();
    for (const l of links) {
      out.set(l.source, (out.get(l.source) ?? 0) + l.value);
      into.set(l.target, (into.get(l.target) ?? 0) + l.value);
    }
    const shown = nodes.filter((n) => Math.max(into.get(n.id) ?? 0, out.get(n.id) ?? 0) > 0);
    for (const n of shown) value.set(n.id, Math.max(into.get(n.id) ?? 0, out.get(n.id) ?? 0));
    const cols = Math.max(...shown.map((n) => n.col)) + 1;
    const byCol = Array.from({ length: cols }, (_, c) => shown.filter((n) => n.col === c));
    const ky = Math.min(...byCol.map((ns) => (H - (ns.length - 1) * PAD) / ns.reduce((s, n) => s + value.get(n.id)!, 0)));
    const step = (W - LABEL_W - NODE_W) / (cols - 1);
    const pos = new Map<string, { x: number; y: number; h: number; inY: number; outY: number }>();
    for (const ns of byCol) {
      let y = 0;
      for (const n of ns) {
        const h = Math.max(1, value.get(n.id)! * ky);
        pos.set(n.id, { x: n.col * step, y, h, inY: y, outY: y });
        y += h + PAD;
      }
    }
    // bands leave and arrive in the order of the nodes they connect, so they never cross at a node
    const order = new Map(shown.map((n, i) => [n.id, i]));
    const bands = links
      .filter((l) => pos.has(l.source) && pos.has(l.target))
      .sort((a, b) => order.get(a.source)! - order.get(b.source)! || order.get(a.target)! - order.get(b.target)!)
      .map((l) => {
        const s = pos.get(l.source)!;
        const t = pos.get(l.target)!;
        const w = l.value * ky;
        const [a0, a1] = [s.outY, t.inY];
        s.outY += w;
        t.inY += w;
        const [x0, x1] = [s.x + NODE_W, t.x];
        const xm = (x0 + x1) / 2;
        const d = `M${x0},${a0} C${xm},${a0} ${xm},${a1} ${x1},${a1} L${x1},${a1 + w} C${xm},${a1 + w} ${xm},${a0 + w} ${x0},${a0 + w} Z`;
        return { id: `${l.source}>${l.target}`, link: l, d };
      });
    // labels: centred on their node, nudged apart within a column so none overlap
    const labels = byCol.flatMap((ns) => {
      const ys = ns.map((n) => pos.get(n.id)!.y + pos.get(n.id)!.h / 2);
      for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + LINE);
      ys[ys.length - 1] = Math.min(ys[ys.length - 1], H - 4);
      for (let i = ys.length - 2; i >= 0; i--) ys[i] = Math.min(ys[i], ys[i + 1] - LINE);
      return ns.map((n, i) => ({ n, y: ys[i], v: value.get(n.id)! }));
    });
    return { shown, pos, bands, labels };
  }, [nodes, links, W, H]);

  const color = new Map(nodes.map((n) => [n.id, n.color]));
  const lit = (id: string) => hover == null || hover === id || id.startsWith(`${hover}>`) || id.endsWith(`>${hover}`);
  const band = layout.bands.find((b) => b.id === hover)?.link;
  const node = layout.labels.find((x) => x.n.id === hover);
  const shown = inView || still;
  return (
    <Box ref={wrap}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block", overflow: "visible" }} role="img" aria-label={label}>
        <defs>
          <clipPath id={clip}>
            <motion.rect x={-1} y={-2} height={H + 4} initial={{ width: still ? W + 2 : 0 }} animate={{ width: shown ? W + 2 : 0 }} transition={{ duration: still ? 0 : 1.2, ease: [0.16, 1, 0.3, 1] }} />
          </clipPath>
        </defs>
        <g clipPath={`url(#${clip})`}>
          {layout.bands.map((b) => (
            <motion.path
              key={b.id}
              className="k-sankey-band"
              initial={false}
              animate={{ d: b.d, opacity: lit(b.id) ? (hover ? 0.75 : 0.42) : 0.14 }}
              transition={{ duration: still ? 0 : 0.6, ease: "easeInOut" }}
              fill={color.get(b.link.target)}
              onMouseEnter={() => setHover(b.id)}
              onMouseLeave={() => setHover(null)}
            >
              <title>{b.link.note}</title>
            </motion.path>
          ))}
          {layout.shown.map((n) => {
            const p = layout.pos.get(n.id)!;
            return (
              <motion.rect
                key={n.id}
                x={p.x}
                width={NODE_W}
                rx={3}
                fill={n.color}
                initial={false}
                animate={{ attrY: p.y, height: p.h }}
                transition={{ duration: still ? 0 : 0.6, ease: "easeInOut" }}
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover(null)}
              />
            );
          })}
        </g>
        {layout.labels.map(({ n, y, v }) => (
          <motion.text
            key={n.id}
            className="k-sankey-label"
            x={layout.pos.get(n.id)!.x + NODE_W + 7}
            initial={still ? false : { opacity: 0, attrY: y }}
            animate={{ opacity: shown ? 1 : 0, attrY: y }}
            transition={{ duration: still ? 0 : 0.5, delay: still ? 0 : 0.25 + n.col * 0.2 }}
            dominantBaseline="middle"
          >
            {n.label}
            <tspan className="k-sankey-value" dx={6}>
              {unit(v)}
            </tspan>
          </motion.text>
        ))}
      </svg>
      <Text as="p" size="1" color="gray" mt="2" aria-live="polite" style={{ minHeight: "1.5em" }}>
        {band ? band.note : node ? `${node.n.label}: ${unit(node.v)}` : "\u00a0"}
      </Text>
      <VisuallyHidden>
        <ul>
          {links.map((l) => (
            <li key={`${l.source}>${l.target}`}>{l.note}</li>
          ))}
        </ul>
      </VisuallyHidden>
    </Box>
  );
}

const RUN: Omit<SNode, "col">[] = [
  { id: "open", label: "Open cases", color: "var(--k-strong)" },
  { id: "contactable", label: "Can be contacted", color: "var(--gray-11)" },
  { id: "hard_stop", label: "Hard stop: no contact", color: "var(--gray-8)" },
  { id: "no_hardship", label: "No hardship signal", color: "var(--gray-10)" }, // above hardship: fewer crossings
  { id: "hardship", label: "Hardship signal", color: "var(--plum-8)" },
  { id: "green", label: "Green: team lead batch", color: "var(--grass-9)" },
  { id: "amber", label: "Amber: assigned agent", color: "var(--amber-9)" },
  { id: "red", label: "Red: specialist review", color: "var(--plum-9)" },
  { id: "wait", label: "No action: waiting is best", color: "var(--gray-7)" },
  { id: "holdout", label: "No action: hold-out", color: "var(--gray-7)" },
  { id: "no_action", label: "No action: other", color: "var(--gray-7)" },
  { id: "cease", label: "Cease contact", color: "var(--gray-8)" },
  { id: "insolvency", label: "Insolvency", color: "var(--gray-8)" },
  { id: "bankruptcy", label: "Bankruptcy", color: "var(--gray-8)" },
  { id: "deceased", label: "Deceased", color: "var(--gray-8)" },
  { id: "other_stop", label: "Other hard stop", color: "var(--gray-8)" },
];
const RUN_COL: Record<string, number> = { open: 0, contactable: 1, hard_stop: 1, hardship: 2, no_hardship: 2 };

/** #104: tonight's open cases through each gate to a card, counts on every node, balances on hover. */
export function RunFlow({ flow, cases }: { flow: Portfolio["flow"]; cases: number }) {
  const name = new Map(RUN.map((n) => [n.id, n.label]));
  const nodes = useMemo(() => RUN.map((n) => ({ ...n, col: RUN_COL[n.id] ?? 3 })), []);
  const links = useMemo(
    () =>
      (flow ?? []).map((f) => ({
        source: f.source,
        target: f.target,
        value: f.cases,
        note: `${name.get(f.source) ?? f.source} to ${name.get(f.target) ?? f.target}: ${count(f.cases)} cases, ${dollars(f.amount)} overdue`,
      })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [flow],
  );
  if (!links.length) return null;
  return (
    <div className="k-card t-ice" style={{ padding: 22 }}>
      <SectionTitle eyebrow="Tonight's run" title={`Where the ${count(cases)} open cases go`} />
      <Text as="p" size="2" color="gray" mb="4" style={{ maxWidth: "72ch" }}>
        Every open case passes the hard-stop gate, then the hardship screen, and ends with a tier or a reason for no action. A case with several hard stops is shown under the strongest one.
      </Text>
      <Sankey nodes={nodes} links={links} height={420} unit={count} label={`Tonight's run: ${count(cases)} open cases from the hard-stop gate and hardship screen to a tier or no action`} />
    </div>
  );
}

const MONEY: SNode[] = [
  { id: "entered", label: "Entered at 1–30 days past due", col: 0, color: "var(--k-strong)" },
  { id: "cured", label: "Cured by day 30", col: 1, color: "var(--grass-9)" },
  { id: "partly_paid", label: "Partly paid, under 30 days", col: 1, color: "var(--grass-7)" },
  { id: "rolled", label: "Rolled past 30 days", col: 1, color: "var(--amber-9)" },
  { id: "not_charged_off", label: "Not charged off", col: 2, color: "var(--gray-8)" },
  { id: "charged_off", label: "Charged off", col: 2, color: "var(--k-red)" },
];

/** #111: a year of new arrears, by overdue at entry, as today and with Kept's base case. */
export function MoneyFlowCard() {
  const { me } = useSession();
  const [m, setM] = useState<MoneyFlow | null>(null);
  const [kept, setKept] = useState(false);
  useEffect(() => {
    if (!me) return;
    let live = true;
    api.portfolioMoney(me).then((x) => live && setM(x), () => undefined); // no report on this machine: no card
    return () => {
      live = false;
    };
  }, [me]);
  const links = useMemo(() => {
    if (!m) return [];
    const name = new Map(MONEY.map((n) => [n.id, n.label]));
    return (kept ? m.with_kept : m.today).map((f) => ({
      source: f.source,
      target: f.target,
      value: f.amount,
      note: `${name.get(f.source)} to ${name.get(f.target)}: ${dollars(f.amount)} overdue, about ${count(f.cases)} cases`,
    }));
  }, [m, kept]);
  if (!m) return null;
  const rolled = (fs: MoneyFlow["today"]) => fs.find((f) => f.target === "rolled")?.amount ?? 0;
  return (
    <div className="k-card t-butter" style={{ padding: 22 }}>
      <SectionTitle
        eyebrow="Business case"
        title={`Where ${dollars(m.overdue)} of new overdue goes in a year`}
        aside={
          <div className="k-tabs" role="group" aria-label="Scenario">
            {[
              [false, "Today"],
              [true, "With Kept (base case)"],
            ].map(([v, t]) => (
              <button key={String(v)} className="k-tab" data-active={kept === v} aria-pressed={kept === v} style={{ height: 34 }} onClick={() => setKept(v as boolean)}>
                {t}
              </button>
            ))}
          </div>
        }
      />
      <Text as="p" size="2" color="gray" mb="4" style={{ maxWidth: "72ch" }}>
        {count(m.cases)} cases a year enter collections at 1–30 days past due. Bands are their overdue at entry, followed to day 30 and to charge-off.
      </Text>
      <Sankey nodes={MONEY} links={links} height={300} unit={dollars} label={`A year of new overdue, ${dollars(m.overdue)}, split into cured, partly paid and rolled, and rolled into charged off or not`} />
      <Grid columns={{ initial: "1", sm: "3" }} gap="2" mt="3">
        <Fact label="Rolled past 30 days" value={dollars(rolled(kept ? m.with_kept : m.today))} note={kept ? `${dollars(rolled(m.today))} today` : "of overdue at entry"} />
        <Fact label="Balance charged off a year" value={dollars(kept ? m.written_off_kept : m.written_off)} note={kept && m.written_off_kept === m.written_off ? "unchanged in the base case" : "rolled cases that charge off"} />
        <Fact label="Promises dated to payday" value={`+${dollars(m.gain)}`} note="paid a year, base case" />
      </Grid>
      <Text as="p" size="1" color="gray" mt="3" style={{ maxWidth: "80ch" }}>
        With Kept, the base case&apos;s payday gain moves from rolled to paid. The base case counts no cut in the roll rate, so charge-offs stay the same; the high case adds one point. Source: scripts/business_case.py; cured and partly paid split by the warehouse&apos;s past cases.
      </Text>
    </div>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <Flex direction="column" style={{ background: "var(--k-chip)", borderRadius: 14, padding: "10px 12px", minWidth: 0 }}>
      <Text size="1" color="gray">
        {label}
      </Text>
      <Text size="4" className="tabular" style={{ letterSpacing: "-0.02em" }}>
        {value}
      </Text>
      <Text size="1" color="gray">
        {note}
      </Text>
    </Flex>
  );
}

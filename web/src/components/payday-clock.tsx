"use client";

import { CodeIcon } from "@radix-ui/react-icons";
import { Box, Flex, Grid, Text } from "@radix-ui/themes";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import type { PaydayClock as Clock } from "@/lib/api";
import { SectionTitle } from "./page-header";
import { SqlBlock } from "./sql-block";

type Bucket = Clock["buckets"][number];

const C = 160; // centre of the 320 × 320 face
const R0 = 62; // the lowest kept rate on the scale
const R1 = 132; // the highest
const SPAN = 33; // -15 … +15 days and a two-day seam at the bottom for the scale: one turn

const pct = (v: number, dp = 1) => `${(v * 100).toFixed(dp)}%`;
const when = (d: number) =>
  d === 0 ? "Due on payday" : d < 0 ? `Due ${-d} day${d === -1 ? "" : "s"} before payday` : `Due ${d} day${d === 1 ? "" : "s"} after payday`;

/** Point at `days` around the face (payday at 12 o'clock, after it clockwise) and radius r. */
function at(days: number, r: number): [number, number] {
  const a = (days / SPAN) * 2 * Math.PI - Math.PI / 2;
  return [C + r * Math.cos(a), C + r * Math.sin(a)];
}

function arc(days: number, r: number) {
  const half = 0.5 - 0.08; // a hairline gap between neighbouring days
  const [x0, y0] = at(days - half, r);
  const [x1, y1] = at(days + half, r);
  return `M${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1}`;
}

/** Weighted kept rate over the buckets whose days fall in [lo, hi]. */
function rate(bs: Bucket[], lo: number, hi: number) {
  const xs = bs.filter((b) => b.days >= lo && b.days <= hi);
  const n = xs.reduce((a, b) => a + b.promises, 0);
  return n ? xs.reduce((a, b) => a + b.kept_rate * b.promises, 0) / n : null;
}

/** The pay-cycle clock: each day from payday is an arc around the face (payday at the top, days after it clockwise,
 * days before it anticlockwise), its distance from the centre the kept rate and its thickness the number of promises. */
export function PaydayClock({ c }: { c: Clock }) {
  const [hover, setHover] = useState<number | null>(null);
  const [sql, setSql] = useState(false);
  const still = useReducedMotion() ?? false;
  const bs = c.buckets;
  if (!bs.length) return null;
  const rates = bs.map((b) => b.kept_rate);
  const lo = Math.floor((Math.min(...rates) - 0.01) * 20) / 20; // to the 5% below
  const hi = Math.ceil((Math.max(...rates) + 0.01) * 20) / 20;
  const r = (v: number) => R0 + ((v - lo) / (hi - lo)) * (R1 - R0);
  const maxN = Math.max(...bs.map((b) => b.promises));
  const thick = (n: number) => 2.5 + (n / maxN) * 15;
  const rings: number[] = [];
  for (let v = lo; v <= hi + 1e-9; v += 0.05) rings.push(Math.round(v * 100) / 100);
  const shown = bs.find((b) => b.days === (hover ?? 0)) ?? bs[0];
  const on = rate(bs, 0, 0);
  const before = rate(bs, -3, -1);
  const after = rate(bs, 1, 3);

  return (
    <div className="k-card" style={{ padding: 22 }}>
      <SectionTitle eyebrow="Pay cycle" title="Promise-kept rate around payday" mb="1" />
      <Text as="p" size="1" color="gray" mb="4">
        Each arc is one day from the customer&apos;s nearest recorded payday to the promise&apos;s due date. Distance from the centre is the share kept in full;
        thickness is the number of promises; the dashed ring is the rate over all of them.
      </Text>
      <Grid columns={{ initial: "1", md: "minmax(0, 340px) minmax(0, 1fr)" }} gap="5" align="center">
        <div className="k-clock t-ice">
          <svg viewBox="0 0 320 320" role="img" aria-label={`Kept rate by days from payday: ${on != null ? pct(on) : "n/a"} on payday`}>
            {rings.map((v) => (
              <circle key={v} cx={C} cy={C} r={r(v)} className="k-clock-ring" />
            ))}
            <circle cx={C} cy={C} r={r(c.kept_rate)} className="k-clock-mean" />
            {rings.map((v) => (
              <text key={v} x={C} y={C + r(v)} textAnchor="middle" dominantBaseline="middle" className="k-clock-scale">
                {Math.round(v * 100)}%
              </text>
            ))}
            {[-14, -7, 0, 7, 14].map((d) => {
              const [x, y] = at(d, R1 + 16);
              return (
                <text key={d} x={x} y={y} textAnchor="middle" dominantBaseline="middle" className="k-clock-label" data-on={d === 0}>
                  {d === 0 ? "Payday" : d > 0 ? `+${d}` : `−${-d}`}
                </text>
              );
            })}
            {bs.map((b) => (
              <motion.path
                key={b.days}
                d={arc(b.days, r(b.kept_rate))}
                className="k-clock-arc"
                data-payday={b.days === 0}
                data-dim={hover != null && hover !== b.days}
                strokeWidth={thick(b.promises)}
                tabIndex={0}
                aria-label={`${when(b.days)}: ${pct(b.kept_rate)} kept of ${b.promises.toLocaleString("en-CA")} promises`}
                onMouseEnter={() => setHover(b.days)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(b.days)}
                onBlur={() => setHover(null)}
                initial={still ? false : { pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.5, delay: 0.1 + Math.abs(b.days) * 0.02 }}
              />
            ))}
            <text x={C} y={C - 8} textAnchor="middle" className="k-clock-big">
              {pct(shown.kept_rate)}
            </text>
            <text x={C} y={C + 12} textAnchor="middle" className="k-clock-sub">
              {shown.days === 0 ? "on payday" : shown.days < 0 ? `${-shown.days} d before` : `${shown.days} d after`}
            </text>
            <text x={C} y={C + 27} textAnchor="middle" className="k-clock-sub">
              {shown.promises.toLocaleString("en-CA")} promises
            </text>
          </svg>
        </div>
        <Box>
          <Flex direction="column" gap="2" mb="4">
            <Stat label="Due on payday" v={on} strong />
            <Stat label="Due 1 to 3 days before" v={before} />
            <Stat label="Due 1 to 3 days after" v={after} />
            <Stat label="All promises shown" v={c.kept_rate} dashed />
          </Flex>
          <Text as="p" size="1" color="gray" mb="2">
            {when(shown.days)}: {pct(shown.kept_rate)} kept in full
            {shown.money_rate != null && <>, {pct(shown.money_rate)} of the promised money paid</>}.
          </Text>
          <Text as="p" size="1" color="gray">
            Resolved promises with a recorded payday within 40 days on both sides; days with under 50 customers are left out. The spikes at 7 and 14 days are
            paydays of customers paid weekly or every two weeks, which the deposit data does not record.
          </Text>
          <button className="k-text-btn" style={{ marginTop: 8, marginLeft: -8 }} onClick={() => setSql((s) => !s)} aria-expanded={sql}>
            <CodeIcon style={{ verticalAlign: -2, marginRight: 4 }} />
            {sql ? "Hide the SQL" : "Show the SQL"}
          </button>
          <AnimatePresence initial={false}>
            {sql && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                style={{ overflow: "hidden" }}
              >
                <SqlBlock sql={c.sql} />
              </motion.div>
            )}
          </AnimatePresence>
        </Box>
      </Grid>
    </div>
  );
}

function Stat({ label, v, strong = false, dashed = false }: { label: string; v: number | null; strong?: boolean; dashed?: boolean }) {
  return (
    <Flex justify="between" align="baseline" className="k-clock-stat" data-strong={strong} data-dashed={dashed}>
      <Text size="2">{label}</Text>
      <Text size={strong ? "5" : "3"} weight={strong ? "bold" : "regular"} className="tabular">
        {v == null ? "—" : pct(v)}
      </Text>
    </Flex>
  );
}

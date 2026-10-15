"use client";

import { Flex, Grid, Text } from "@radix-ui/themes";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { api, type Workload } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Stat } from "./model-panels";
import { SectionTitle } from "./page-header";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const n0 = (v: number) => Math.round(v).toLocaleString("en-CA");
const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
const day = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString("en-CA", { day: "numeric", month: "short" });

/** #115: tonight's proposed calls by weekday and hour (operating time zone) against the call team's hourly
 * capacity. Shade: share of capacity used; hatched: more calls than capacity. Renders nothing without data. */
export function WorkloadHeatmap() {
  const { me } = useSession();
  const [w, setW] = useState<Workload | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const calm = useReducedMotion();
  useEffect(() => {
    if (!me) return;
    let live = true;
    api.portfolioWorkload(me).then((x) => live && setW(x), () => undefined);
    return () => {
      live = false;
    };
  }, [me]);

  const grid = useMemo(() => {
    if (!w || w.cells.length === 0) return null;
    const at = new Map(w.cells.map((c) => [`${c.weekday}-${c.hour}`, c]));
    const hours = w.cells.map((c) => c.hour);
    const lo = Math.min(...hours);
    const cols = Array.from({ length: Math.max(...hours) - lo + 1 }, (_, i) => lo + i);
    const over = w.cells.filter((c) => c.calls > c.capacity);
    const peak = w.cells.reduce((a, c) => (c.calls > a.calls ? c : a), w.cells[0]);
    return { at, cols, over, peak, beyond: over.reduce((s, c) => s + c.calls - c.capacity, 0) };
  }, [w]);
  if (!w || !grid || w.calls === 0) return null;

  const h = hover ? grid.at.get(hover) : undefined;
  const [hd, hr] = hover ? hover.split("-").map(Number) : [0, 0];
  const readout = hover
    ? `${DAYS[hd]} ${hh(hr)}–${hh(hr + 1)} · ${n0(h?.calls ?? 0)} calls proposed · ` +
      (h && h.capacity > 0 ? `capacity ${n0(h.capacity)} (${Math.round((100 * h.calls) / h.capacity)}% used)` : "no call capacity in this hour")
    : "Point at an hour to see its calls and capacity.";
  return (
    <div className="k-card t-ice" style={{ padding: 22, marginTop: "var(--space-5)" }}>
      <SectionTitle eyebrow="Agent workload" title="Proposed calls against call capacity" />
      <Grid columns={{ initial: "2", sm: "4" }} gap="2" mb="3">
        <Stat label="Calls proposed" value={n0(w.calls)} />
        <Stat label="Busiest hour" value={`${DAYS[grid.peak.weekday].slice(0, 3)} ${hh(grid.peak.hour)}`} note={`${n0(grid.peak.calls)} calls`} />
        <Stat label="Hours over capacity" value={n0(grid.over.length)} note={`of ${n0(w.cells.filter((c) => c.calls > 0).length)} hours with calls`} />
        <Stat label="Calls beyond capacity" value={n0(grid.beyond)} note={`${Math.round((100 * grid.beyond) / w.calls)}% of proposed calls`} />
      </Grid>
      <div
        className="k-load"
        style={{ gridTemplateColumns: `36px repeat(${grid.cols.length}, minmax(0, 1fr))` }}
        role="img"
        aria-label={`Proposed calls by weekday and hour against capacity: ${grid.over.length} hours over capacity, ${n0(grid.beyond)} calls beyond it.`}
        onMouseLeave={() => setHover(null)}
      >
        <span />
        {grid.cols.map((c) => (
          <Text key={c} size="1" color="gray" align="center" className="tabular k-load-hour">
            {String(c).padStart(2, "0")}
          </Text>
        ))}
        {DAYS.map((d, wd) => (
          <Row key={d} wd={wd} cols={grid.cols} at={grid.at} hover={hover} setHover={setHover} calm={!!calm} />
        ))}
      </div>
      <Text as="div" size="1" color="gray" mt="2" className="tabular" style={{ minHeight: 18 }} aria-live="polite">
        {readout}
      </Text>
      <Flex gap="4" mt="3" wrap="wrap" align="center">
        <Flex gap="2" align="center">
          <span className="k-load-scale" aria-hidden />
          <Text size="1" color="gray">
            Share of capacity used, 0% to 100%
          </Text>
        </Flex>
        <Flex gap="2" align="center">
          <span className="k-load-swatch" data-over="true" aria-hidden />
          <Text size="1" color="gray">
            Over capacity
          </Text>
        </Flex>
        <Flex gap="2" align="center">
          <span className="k-load-swatch" aria-hidden />
          <Text size="1" color="gray">
            No call capacity
          </Text>
        </Flex>
      </Flex>
      <Text as="p" size="1" color="gray" mt="3">
        Each call counts in the hour its window starts, in the bank&apos;s operating time zone ({w.time_zone}).
        {w.capacity_from && w.capacity_to && (
          <>
            {" "}
            Capacity is the call team&apos;s outbound attempts for {day(w.capacity_from)} to {day(w.capacity_to)}, each shift band spread evenly over its hours.
          </>
        )}
      </Text>
    </div>
  );
}

function Row({
  wd,
  cols,
  at,
  hover,
  setHover,
  calm,
}: {
  wd: number;
  cols: number[];
  at: Map<string, Workload["cells"][number]>;
  hover: string | null;
  setHover: (k: string) => void;
  calm: boolean;
}) {
  return (
    <>
      <Text size="1" color="gray" className="k-load-day">
        {DAYS[wd].slice(0, 3)}
      </Text>
      {cols.map((hr, i) => {
        const k = `${wd}-${hr}`;
        const c = at.get(k);
        const cap = c?.capacity ?? 0;
        const calls = c?.calls ?? 0;
        const over = calls > cap;
        const share = cap > 0 ? Math.min(calls / cap, 1) : 0;
        return (
          <motion.span
            key={k}
            className="k-load-cell"
            data-over={over}
            data-none={cap === 0 && !over}
            data-hover={hover === k}
            style={cap > 0 && !over ? { background: `color-mix(in srgb, var(--k-ice-ink) ${Math.round(8 + 84 * share)}%, var(--k-chip))` } : undefined}
            title={`${DAYS[wd]} ${hh(hr)}: ${n0(calls)} calls, capacity ${n0(cap)}`}
            onMouseEnter={() => setHover(k)}
            onClick={() => setHover(k)}
            initial={calm ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: calm ? 0 : wd * 0.04 + i * 0.015 }}
          />
        );
      })}
    </>
  );
}

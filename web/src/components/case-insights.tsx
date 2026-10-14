"use client";

import { ChatBubbleIcon, CheckCircledIcon, CrossCircledIcon, EnvelopeClosedIcon, MobileIcon, TimerIcon } from "@radix-ui/react-icons";
import { Box, Flex, Grid, Text } from "@radix-ui/themes";
import { motion } from "motion/react";
import { useState } from "react";
import { ACTION_LABEL, money, type CaseHistory, type Driver, type NBACard } from "@/lib/api";
import { SectionTitle } from "./page-header";

// diverging pair, validated (dataviz validator, light and dark): toward the action = maple, away = blue
const TOWARD = "var(--k-red)";
const AWAY = "var(--viz-1)";

/** Every model input's push on the recommended action (TreeSHAP), both signs, on one zero line. */
export function WhyChart({ card }: { card: NBACard }) {
  const ds = card.drivers ?? [];
  const [hover, setHover] = useState<string | null>(null);
  if (!ds.length) return null;
  const max = Math.max(...ds.map((d) => Math.abs(d.pts)), 1);
  const action = card.proposal ? ACTION_LABEL[card.proposal.action] : "the recommendation";
  return (
    <div className="k-card" style={{ padding: 22 }}>
      <SectionTitle
        eyebrow={`Explainability · ${action}`}
        title="Every factor, both ways"
        mb="1"
        aside={
          <Flex gap="4">
            <Swatch color={TOWARD} label="Pushes toward it" />
            <Swatch color={AWAY} label="Pushes away" />
          </Flex>
        }
      />
      <Text as="p" size="1" color="gray" mb="4">
        Percentage points of paid-in-14-days over waiting, per feature (TreeSHAP on the model that scored it). Fixed labels; no LLM text.
      </Text>
      <Grid columns={{ initial: "1", lg: "minmax(0, 1fr) 260px" }} gap="5" align="center">
        <div role="list" aria-label="Feature contributions">
          {ds.map((d, i) => (
            <DriverRow key={d.feature} d={d} max={max} i={i} hover={hover === d.feature} onHover={(on) => setHover(on ? d.feature : null)} />
          ))}
        </div>
        <DriverRadar drivers={ds} />
      </Grid>
    </div>
  );
}

/** Model inputs fall into six families; the radar shows how hard each family pushes (sum of |TreeSHAP|). */
const FAMILIES: { name: string; match: RegExp }[] = [
  { name: "Similar cases", match: /cohort|similar/ },
  { name: "Cash flow", match: /cash|utilis|balance|spare|income|deposit/ },
  { name: "Payday", match: /payroll|pay_freq|payday|salary/ },
  { name: "Promises", match: /promise|ptp|kept/ },
  { name: "Reachability", match: /answer|contact|rpc|link|channel|call|sms|email/ },
  { name: "Delinquency", match: /dpd|bucket|overdue|arrears|30plus/ },
];

/** A soft closed curve through the points (Catmull-Rom as cubic Béziers): the studio's blob, not a polygon. */
function blob(pts: [number, number][]) {
  const n = pts.length;
  const p = (i: number) => pts[(i + n) % n];
  let d = `M${p(0)[0]},${p(0)[1]}`;
  for (let i = 0; i < n; i++) {
    const [x0, y0] = p(i - 1);
    const [x1, y1] = p(i);
    const [x2, y2] = p(i + 1);
    const [x3, y3] = p(i + 2);
    d += ` C${x1 + (x2 - x0) / 6},${y1 + (y2 - y0) / 6} ${x2 - (x3 - x1) / 6},${y2 - (y3 - y1) / 6} ${x2},${y2}`;
  }
  return d + "Z";
}

export function DriverRadar({ drivers }: { drivers: Driver[] }) {
  const fam = FAMILIES.map((f) => {
    const ds = drivers.filter((d) => f.match.test(d.feature));
    return { name: f.name, weight: ds.reduce((a, d) => a + Math.abs(d.pts), 0), net: ds.reduce((a, d) => a + d.pts, 0) };
  });
  const max = Math.max(...fam.map((f) => f.weight), 0.1);
  const top = fam.reduce((a, f) => (f.weight > a.weight ? f : a), fam[0]);
  const [hover, setHover] = useState<string | null>(null);
  const shown = fam.find((f) => f.name === hover) ?? top;
  const C = 130;
  const R = 76;
  const at = (i: number, r: number): [number, number] => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / fam.length;
    return [C + r * Math.cos(a), C + r * Math.sin(a)];
  };
  const pts = fam.map((f, i) => at(i, 14 + (f.weight / max) * (R - 14)));
  const ti = fam.indexOf(shown);
  const [tx, ty] = pts[ti];
  return (
    <div className="k-radar t-lilac" aria-label="How hard each family of inputs pushes">
      <svg viewBox="0 0 260 260" role="img">
        {[0.33, 0.66, 1].map((k) => (
          <polygon key={k} points={fam.map((_, i) => at(i, R * k).join(",")).join(" ")} fill="none" stroke="var(--k-dash)" strokeWidth={k === 1 ? 1.2 : 0.8} />
        ))}
        {fam.map((_, i) => {
          const [x, y] = at(i, R);
          return <line key={i} x1={C} y1={C} x2={x} y2={y} stroke="var(--k-dash)" strokeWidth={0.8} />;
        })}
        <motion.path
          d={blob(pts)}
          fill="var(--t-2)"
          stroke="var(--t-ink)"
          strokeWidth={1.5}
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          style={{ transformOrigin: "130px 130px" }}
          transition={{ type: "spring", stiffness: 120, damping: 18 }}
        />
        {fam.map((f, i) => {
          const [x, y] = at(i, R + 16);
          return (
            <text
              key={f.name}
              x={x}
              y={y}
              textAnchor={Math.abs(x - C) < 8 ? "middle" : x > C ? "start" : "end"}
              dominantBaseline="middle"
              className="k-radar-axis"
              data-on={f.name === shown.name}
              onMouseEnter={() => setHover(f.name)}
              onMouseLeave={() => setHover(null)}
            >
              {f.name}
            </text>
          );
        })}
        {pts.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i === ti ? 4.5 : 3} fill="var(--k-frame)" stroke="var(--t-ink)" strokeWidth={1.5} onMouseEnter={() => setHover(fam[i].name)} onMouseLeave={() => setHover(null)} />
        ))}
      </svg>
      {shown.weight > 0 && (
        <span
          className="k-pill-tip"
          data-below={ty < C}
          style={{ left: `${Math.min(74, Math.max(26, (tx / 260) * 100))}%`, top: `${(ty / 260) * 100}%` }}
        >
          net {shown.net >= 0 ? "+" : "−"}
          {Math.abs(shown.net).toFixed(1)} pts
        </span>
      )}
    </div>
  );
}

function DriverRow({ d, max, i, hover, onHover }: { d: Driver; max: number; i: number; hover: boolean; onHover: (on: boolean) => void }) {
  const w = (Math.abs(d.pts) / max) * 50; // % of the track; the zero line sits at 50%
  const pos = d.pts > 0;
  return (
    <div
      role="listitem"
      className="k-why-row"
      data-hover={hover}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      title={`${d.label}${d.value ? ` (${d.value})` : ""}: ${pos ? "+" : ""}${d.pts} pts`}
    >
      <Text size="2" truncate>
        {d.label}
        {d.value && (
          <Text color="gray" size="1">
            {" "}
            · {d.value}
          </Text>
        )}
      </Text>
      <div className="k-why-track">
        <span className="k-why-zero" />
        <motion.span
          className="k-why-bar"
          style={{ background: pos ? TOWARD : AWAY, [pos ? "left" : "right"]: "50%", borderRadius: pos ? "0 4px 4px 0" : "4px 0 0 4px" }}
          initial={{ width: 0 }}
          animate={{ width: `${w}%` }}
          transition={{ type: "spring", stiffness: 140, damping: 22, delay: 0.05 + i * 0.03 }}
        />
      </div>
      <Text size="2" className="tabular" align="right" weight={hover ? "bold" : "regular"}>
        {pos ? "+" : "−"}
        {Math.abs(d.pts).toFixed(1)}
      </Text>
    </div>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <Flex align="center" gap="2">
      <span style={{ width: 10, height: 10, borderRadius: 3, background: color }} />
      <Text size="1" color="gray">
        {label}
      </Text>
    </Flex>
  );
}

const CHANNEL_ICON: Record<string, React.ReactNode> = {
  Call: <MobileIcon />,
  SMS: <ChatBubbleIcon />,
  Email: <EnvelopeClosedIcon />,
};

/** The case's story: stat tiles, month-end small multiples (one scale each, never two axes), and the timeline. */
export function HistoryPanel({ h }: { h: CaseHistory }) {
  const [all, setAll] = useState(false);
  const shown = all ? h.events : h.events.slice(0, 10);
  return (
    <div className="k-card" style={{ padding: 22 }}>
      <SectionTitle eyebrow="From the warehouse" title="History" />
      <Grid columns={{ initial: "2", sm: "4" }} gap="2" mb="4">
        <Tile label="Contacts" value={String(h.contacts)} />
        <Tile label="Reached the customer" value={h.right_party_rate == null ? "—" : `${Math.round(h.right_party_rate * 100)}%`} />
        <Tile label="Promises kept" value={`${h.promises_kept} of ${h.promises_kept + h.promises_broken}`} />
        <Tile label="Open promises" value={String(h.promises_open)} />
      </Grid>
      {h.months.length > 1 && (
        <Grid columns={{ initial: "1", sm: "2" }} gap="3" mb="4">
          <MonthBars title="Month-end balance" points={h.months.map((m) => ({ month: m.month, v: Number(m.balance) }))} fmt={(v) => money(v)} />
          <MonthBars title="Paid in the month" points={h.months.map((m) => ({ month: m.month, v: Number(m.paid) }))} fmt={(v) => money(v)} accent />
        </Grid>
      )}
      <Flex direction="column">
        {shown.map((e, i) => (
          <motion.div
            key={`${e.at}-${i}`}
            className="k-tl-row"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0, transition: { delay: Math.min(i, 10) * 0.025 } }}
            style={{ contentVisibility: "auto", containIntrinsicSize: "auto 56px" }}
          >
            <span className="k-chip" style={{ width: 30, height: 30, borderRadius: 10, color: e.tone === "good" ? "var(--grass-10)" : e.tone === "bad" ? "var(--red-10)" : undefined }}>
              {e.kind === "promise" ? (
                e.tone === "bad" ? (
                  <CrossCircledIcon />
                ) : e.tone === "good" ? (
                  <CheckCircledIcon />
                ) : (
                  <TimerIcon />
                )
              ) : (
                (CHANNEL_ICON[e.title.split(",")[0]] ?? <ChatBubbleIcon />)
              )}
            </span>
            <Box style={{ minWidth: 0, flex: 1 }}>
              <Flex justify="between" gap="3">
                <Text size="2" weight="medium">
                  {e.title}
                </Text>
                <Text size="1" color="gray" className="tabular" style={{ whiteSpace: "nowrap" }}>
                  {new Date(e.at).toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric" })}
                </Text>
              </Flex>
              <Text as="div" size="1" color="gray">
                {e.detail}
                {e.amount != null && ` · ${money(e.amount, true)}`}
              </Text>
            </Box>
          </motion.div>
        ))}
      </Flex>
      {h.events.length > 10 && (
        <button className="k-text-btn" style={{ marginTop: 8 }} onClick={() => setAll((a) => !a)}>
          {all ? "Show fewer" : `Show all ${h.events.length}`}
        </button>
      )}
      {h.events.length === 0 && (
        <Text size="2" color="gray">
          No contacts or promises recorded on this case yet.
        </Text>
      )}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: "var(--k-chip)", borderRadius: 16, padding: "12px 14px" }}>
      <Text as="div" size="1" color="gray">
        {label}
      </Text>
      <Text as="div" size="5" className="tabular" style={{ letterSpacing: "-0.02em" }}>
        {value}
      </Text>
    </div>
  );
}

function MonthBars({ title, points, fmt, accent = false }: { title: string; points: { month: string; v: number }[]; fmt: (v: number) => string; accent?: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...points.map((p) => p.v), 1);
  const last = points[points.length - 1];
  const at = hover ?? points.length - 1;
  return (
    <div style={{ background: "var(--k-chip)", borderRadius: 16, padding: 14 }}>
      <Flex justify="between" align="baseline">
        <Text size="1" color="gray">
          {title}
        </Text>
        <Text size="2" weight="medium" className="tabular">
          {fmt(points[at]?.v ?? last.v)}
          <Text size="1" color="gray">
            {" "}
            · {new Date(points[at]?.month ?? last.month).toLocaleDateString("en-CA", { month: "short", year: "2-digit" })}
          </Text>
        </Text>
      </Flex>
      <div className="k-months" onMouseLeave={() => setHover(null)}>
        {points.map((p, i) => (
          <span key={p.month} className="k-month-hit" onMouseEnter={() => setHover(i)} title={`${p.month}: ${fmt(p.v)}`}>
            <motion.span
              className="k-month-bar"
              style={{ background: accent ? "var(--k-red)" : "var(--k-strong)", opacity: hover === null || hover === i ? 1 : 0.45 }}
              initial={{ height: 0 }}
              animate={{ height: `${Math.max(4, (p.v / max) * 100)}%` }}
              transition={{ type: "spring", stiffness: 160, damping: 24, delay: i * 0.03 }}
            />
          </span>
        ))}
      </div>
    </div>
  );
}

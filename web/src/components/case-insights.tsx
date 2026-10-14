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
      <div role="list" aria-label="Feature contributions">
        {ds.map((d, i) => (
          <DriverRow key={d.feature} d={d} max={max} i={i} hover={hover === d.feature} onHover={(on) => setHover(on ? d.feature : null)} />
        ))}
      </div>
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

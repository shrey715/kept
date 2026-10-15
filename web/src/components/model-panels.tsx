"use client";

import { CheckIcon, Cross2Icon } from "@radix-ui/react-icons";
import { Box, Flex, Grid, Text } from "@radix-ui/themes";
import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { ACTION_LABEL, type Action } from "@/lib/api";
import { SectionTitle } from "./page-header";

// The report JSON as the scripts write it (scripts/model_card.py, fairness_report, drift_report)
type Card = {
  written: string;
  promise: { rows_test: number; auc: number; brier: number; kept_rate: number; cutoff: string; reliability: { predicted: number; observed: number; n: number }[]; importance: { label: string; share: number }[] };
  uplift: { rows_test: number; qini_any_contact: number; qini_noise: number; cutoff: string; curve: { frac: number; gain: number }[]; random_end: number; importance: Record<string, { label: string; pts: number }[]> };
};
type Fairness = { written: string; attributes: Record<string, { outcomes: Record<string, { ratio: number; flagged: boolean; too_few_events: boolean }> }> };
type Drift = { written: string; headline: string; watch: number; drift: number; rows: { feature: string; psi: number; status: "drift" | "watch" | "stable"; model_input: boolean }[] };
type Invariance = { written: string; cases: number; cards_differ: number; passed: boolean; scrambled: Record<string, string[]> };
// kept nightly's heartbeat (src/kept/cli.py nightly): rewritten after every step; exit is null while it runs
type Nightly = {
  started: string;
  finished: string | null;
  exit: number | null;
  planned: string[];
  steps: { name: string; start: string; seconds: number; exit: number }[];
  gate: "pass" | "block" | null;
  parity: { passed: boolean; mismatch_rate: number | null } | null;
  drift_alarm: string[] | null;
};
export type Governance = { model_card: Card | null; fairness: Fairness | null; drift: Drift | null; invariance?: Invariance | null; nightly?: Nightly | null };

const pct = (v: number, d = 0) => `${(v * 100).toFixed(d)}%`;

export function ModelPanels({ g }: { g: Governance }) {
  return (
    <Grid columns={{ initial: "1", lg: "2" }} gap="3" mt="3">
      {g.nightly?.steps && <Heartbeat n={g.nightly} />}
      {g.model_card?.promise?.reliability && <PromiseCard p={g.model_card.promise} />}
      {g.model_card?.uplift?.curve && <UpliftCard u={g.model_card.uplift} />}
      {g.fairness && <FairnessCard f={g.fairness} inv={g.invariance ?? null} />}
      {g.drift && <DriftCard d={g.drift} />}
    </Grid>
  );
}

export function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div style={{ background: "var(--k-chip)", borderRadius: 14, padding: "10px 12px", minWidth: 0 }}>
      <Text as="div" size="1" color="gray">
        {label}
      </Text>
      <Text as="div" size="4" className="tabular" style={{ letterSpacing: "-0.02em" }}>
        {value}
      </Text>
      {note && (
        <Text as="div" size="1" color="gray">
          {note}
        </Text>
      )}
    </div>
  );
}

/** Reliability diagram: each bin's mean predicted chance against how often promises were kept; the diagonal is perfect. */
function PromiseCard({ p }: { p: Card["promise"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 300;
  const H = 220;
  const x = (v: number) => 30 + v * (W - 40);
  const y = (v: number) => H - 24 - v * (H - 40);
  const maxN = Math.max(...p.reliability.map((r) => r.n));
  const h = hover == null ? null : p.reliability[hover];
  return (
    <div className="k-card t-lilac" style={{ padding: 22 }}>
      <SectionTitle eyebrow="Promise model" title="Calibration on held-out promises" />
      <Grid columns="3" gap="2" mb="3">
        <Stat label="AUC" value={p.auc.toFixed(3)} />
        <Stat label="Brier score" value={p.brier.toFixed(3)} />
        <Stat label="Held-out promises" value={p.rows_test.toLocaleString("en-CA")} note={`made after ${p.cutoff}`} />
      </Grid>
      <Grid columns={{ initial: "1", sm: "1fr 1fr" }} gap="4" align="start">
        <Box>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: 360, height: "auto", display: "block" }} role="img" aria-label="Reliability diagram">
            {[0, 0.25, 0.5, 0.75, 1].map((t) => (
              <g key={t}>
                <line x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} stroke="var(--k-line)" />
                <text x={x(0) - 6} y={y(t) + 3} textAnchor="end" fontSize="9" fill="var(--gray-10)">
                  {pct(t)}
                </text>
                <text x={x(t)} y={H - 8} textAnchor="middle" fontSize="9" fill="var(--gray-10)">
                  {pct(t)}
                </text>
              </g>
            ))}
            <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} stroke="var(--gray-9)" strokeDasharray="4 4" />
            <motion.polyline
              fill="none"
              stroke="var(--k-red)"
              strokeWidth="2"
              points={p.reliability.map((r) => `${x(r.predicted)},${y(r.observed)}`).join(" ")}
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.9 }}
            />
            {p.reliability.map((r, i) => (
              <circle
                key={i}
                cx={x(r.predicted)}
                cy={y(r.observed)}
                r={4 + 5 * Math.sqrt(r.n / maxN)}
                fill="var(--k-red)"
                stroke="var(--t-bg, var(--k-card))"
                strokeWidth="2"
                opacity={hover == null || hover === i ? 1 : 0.4}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              />
            ))}
          </svg>
          <Text as="div" size="1" color="gray">
            {h ? `Predicted ${pct(h.predicted, 1)} · kept ${pct(h.observed, 1)} · ${h.n.toLocaleString("en-CA")} promises` : "x: predicted chance · y: share kept · dot size: promises · dashed: perfect"}
          </Text>
        </Box>
        <Box>
          <Text as="div" size="1" color="gray" mb="2">
            What drives it (share of |TreeSHAP|)
          </Text>
          <Flex direction="column" gap="2">
            {p.importance.map((f, i) => (
              <Box key={f.label}>
                <Flex justify="between" gap="2">
                  <Text size="1" truncate>
                    {f.label}
                  </Text>
                  <Text size="1" className="tabular">
                    {pct(f.share)}
                  </Text>
                </Flex>
                <div className="k-act-track" style={{ height: 6, marginTop: 3 }}>
                  <motion.span className="k-act-bar" style={{ background: "var(--k-strong)" }} initial={{ width: 0 }} animate={{ width: `${(f.share / p.importance[0].share) * 100}%` }} transition={{ delay: i * 0.05 }} />
                </div>
              </Box>
            ))}
          </Flex>
        </Box>
      </Grid>
    </div>
  );
}

/** Qini curve: extra payments gained by contacting the model's top-ranked cases first, against random order. */
function UpliftCard({ u }: { u: Card["uplift"] }) {
  const actions = Object.keys(u.importance);
  const [a, setA] = useState(actions[0]);
  const W = 300;
  const H = 200;
  const gains = u.curve.map((c) => c.gain);
  const lo = Math.min(0, ...gains);
  const hi = Math.max(u.random_end, ...gains, 1);
  const x = (v: number) => 12 + v * (W - 20);
  const y = (v: number) => H - 20 - ((v - lo) / (hi - lo)) * (H - 36);
  return (
    <div className="k-card t-lilac" style={{ padding: 22 }}>
      <SectionTitle eyebrow="Uplift model" title="Qini curve on held-out decisions" />
      <Grid columns="3" gap="2" mb="3">
        <Stat label="Qini, any contact" value={u.qini_any_contact.toFixed(4)} note={`noise ± ${u.qini_noise.toFixed(4)}`} />
        <Stat label="Held-out decisions" value={u.rows_test.toLocaleString("en-CA")} note={`after ${u.cutoff}`} />
        <Stat label="Gate" value="Champion kept" note="a worse model can't go live" />
      </Grid>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: 420, height: "auto", display: "block", margin: "0 auto" }} role="img" aria-label="Qini curve">
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(0)} stroke="var(--k-line)" />
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(u.random_end)} stroke="var(--gray-9)" strokeDasharray="4 4" />
        <motion.polyline
          fill="none"
          stroke="var(--k-red)"
          strokeWidth="2"
          points={u.curve.map((c) => `${x(c.frac)},${y(c.gain)}`).join(" ")}
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1 }}
        />
        <text x={x(1)} y={H - 6} textAnchor="end" fontSize="9" fill="var(--gray-10)">
          share of cases contacted, best-ranked first →
        </text>
      </svg>
      <Text as="p" size="1" color="gray" mt="1">
        Red: the model&apos;s order · dashed: random order. The gap is small and the gate measures it against noise before any model goes live; timing (payday) is where the measured gain is.
      </Text>
      <Flex gap="2" mt="3" wrap="wrap">
        {actions.map((k) => (
          <button key={k} className="k-tab" data-active={a === k} style={{ height: 30 }} onClick={() => setA(k)}>
            {ACTION_LABEL[k as Action] ?? k}
          </button>
        ))}
      </Flex>
      <Flex direction="column" gap="2" mt="3">
        {(u.importance[a] ?? []).slice(0, 6).map((f, i, all) => (
          <Box key={f.label}>
            <Flex justify="between">
              <Text size="1">{f.label}</Text>
              <Text size="1" className="tabular">
                {f.pts.toFixed(2)} pts
              </Text>
            </Flex>
            <div className="k-act-track" style={{ height: 6, marginTop: 3 }}>
              <motion.span key={a + f.label} className="k-act-bar" style={{ background: "var(--k-red)" }} initial={{ width: 0 }} animate={{ width: `${(f.pts / all[0].pts) * 100}%` }} transition={{ delay: i * 0.04 }} />
            </div>
          </Box>
        ))}
      </Flex>
    </div>
  );
}

/** Selection-rate ratio (lowest group / highest) per protected attribute and outcome; under 0.8 is a flag. */
function FairnessCard({ f, inv }: { f: Fairness; inv: Invariance | null }) {
  const attrs = Object.keys(f.attributes);
  const outcomes = [...new Set(attrs.flatMap((a) => Object.keys(f.attributes[a].outcomes)))];
  return (
    <div className="k-card t-lilac" style={{ padding: 22 }}>
      <SectionTitle eyebrow={`Fairness · ${f.written}`} title="Treatment across protected groups" />
      <Text as="p" size="1" color="gray" mb="3">
        Lowest group&apos;s rate over the highest&apos;s (1.00 = equal). Under 0.80 is flagged (the four-fifths rule); hatched cells have too few events to judge. Protected attributes are never model inputs.
      </Text>
      {inv && (
        <div className="k-invariance" data-ok={inv.passed}>
          <span className="k-checks-dot" aria-hidden>
            {inv.passed ? <CheckIcon /> : <Cross2Icon />}
          </span>
          <Text size="2">
            Scrambling every protected attribute changed <b className="tabular">{inv.cards_differ.toLocaleString("en-CA")}</b> of{" "}
            <span className="tabular">{inv.cases.toLocaleString("en-CA")}</span> cards
            <Text color="gray"> · checked {new Date(inv.written).toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short" })}</Text>
          </Text>
        </div>
      )}
      <Box style={{ overflowX: "auto" }}>
        <div className="k-heat" style={{ gridTemplateColumns: `minmax(140px, 1.4fr) repeat(${outcomes.length}, minmax(70px, 1fr))` }}>
          <span />
          {outcomes.map((o) => (
            <Text key={o} size="1" color="gray" align="center">
              {o}
            </Text>
          ))}
          {attrs.map((a) => (
            <FairRow key={a} a={a} outcomes={outcomes} cells={f.attributes[a].outcomes} />
          ))}
        </div>
      </Box>
    </div>
  );
}

function FairRow({ a, outcomes, cells }: { a: string; outcomes: string[]; cells: Fairness["attributes"][string]["outcomes"] }) {
  return (
    <>
      <Text size="1" style={{ alignSelf: "center" }} truncate>
        {a.replace(/_/g, " ")}
      </Text>
      {outcomes.map((o) => {
        const c = cells[o];
        if (!c) return <span key={o} className="k-heat-cell" data-empty="true" />;
        const tone = c.too_few_events ? undefined : c.flagged || c.ratio < 0.8 ? "var(--k-red)" : undefined;
        return (
          <span
            key={o}
            className="k-heat-cell"
            data-empty={c.too_few_events}
            title={`${a} · ${o}: ratio ${c.ratio.toFixed(2)}${c.flagged ? " (flagged)" : ""}${c.too_few_events ? " (too few events)" : ""}`}
            style={tone ? { background: tone, color: "#fff" } : undefined}
          >
            {c.too_few_events ? "" : c.ratio.toFixed(2)}
          </span>
        );
      })}
    </>
  );
}

/** Population stability (PSI) of each feature, live against training: one bar each, two threshold lines. */
function DriftCard({ d }: { d: Drift }) {
  const rows = [...d.rows].sort((a, b) => b.psi - a.psi).slice(0, 12);
  const cap = 1; // PSI above 1 runs off the scale; its value is printed
  const color = { drift: "var(--k-red)", watch: "var(--amber-9)", stable: "var(--gray-8)" } as const;
  return (
    <div className="k-card t-lilac" style={{ padding: 22 }}>
      <SectionTitle eyebrow={`Drift · ${d.written}`} title="Feature drift since training" />
      <Text as="p" size="1" color="gray" mb="3">
        {d.headline} Lines: watch at {d.watch}, drift at {d.drift}. Drift on a model input pauses promotion until a retrain is checked.
      </Text>
      <Flex direction="column" gap="2">
        {rows.map((r, i) => (
          <Box key={r.feature} title={`${r.feature}: PSI ${r.psi.toFixed(3)} (${r.status})${r.model_input ? " · model input" : ""}`}>
            <Flex justify="between" gap="2">
              <Text size="1" truncate>
                {r.feature.replace(/_/g, " ")}
                {r.model_input && (
                  <Text color="gray" size="1">
                    {" "}
                    · model input
                  </Text>
                )}
              </Text>
              <Text size="1" className="tabular">
                {r.psi.toFixed(2)}
              </Text>
            </Flex>
            <div className="k-act-track" style={{ height: 8, marginTop: 3 }}>
              <span className="k-act-wait" style={{ left: `${(d.watch / cap) * 100}%`, borderLeftStyle: "dotted" }} />
              <span className="k-act-wait" style={{ left: `${(d.drift / cap) * 100}%` }} />
              <motion.span className="k-act-bar" style={{ background: color[r.status] }} initial={{ width: 0 }} animate={{ width: `${Math.min(r.psi / cap, 1) * 100}%` }} transition={{ delay: i * 0.04 }} />
            </div>
          </Box>
        ))}
      </Flex>
    </div>
  );
}

const STEP: Record<string, string> = {
  land: "Land raw files",
  silver: "Silver models",
  match: "Identity matching",
  gold: "Gold models",
  gate: "Quality gate",
  extract: "Note extraction",
  features: "Features and online store",
  parity: "Offline/online parity",
  score: "Score open cases",
  invariance: "Protected-attribute check",
};
const took = (s: number) =>
  s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
const clock = (ms: number) => new Date(ms).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit" });

function Badge({ tone, label, value }: { tone: "ok" | "bad" | "idle"; label: string; value: string }) {
  return (
    <span className="k-beat-badge" data-tone={tone}>
      <span className="k-beat-icon" aria-hidden>
        {tone === "ok" ? <CheckIcon /> : tone === "bad" ? <Cross2Icon /> : null}
      </span>
      <Text size="1" color="gray">
        {label}
      </Text>
      <Text size="1" weight="medium" className="tabular">
        {value}
      </Text>
    </span>
  );
}

/** #114: the last `kept nightly` as a Gantt strip, each step a bar at its real start and length, with the
 * gate, parity and drift results as badges. Steps planned but not reached are listed as not run. */
function Heartbeat({ n }: { n: Nightly }) {
  const calm = useReducedMotion();
  const t0 = Date.parse(n.started);
  const end = Math.max(t0 + 1000, ...n.steps.map((s) => Date.parse(s.start) + s.seconds * 1000));
  const span = end - t0;
  const ran = new Set(n.steps.map((s) => s.name));
  const rows = [...n.steps, ...n.planned.filter((p) => !ran.has(p)).map((name) => ({ name, start: null, seconds: 0, exit: null }))];
  const running = n.exit == null;
  const failed = n.steps.find((s) => s.exit !== 0);
  const status = running
    ? { tone: "idle" as const, value: "In progress" }
    : n.exit === 0
      ? { tone: "ok" as const, value: `Completed in ${took(span / 1000)}` }
      : { tone: "bad" as const, value: `Stopped at ${STEP[failed?.name ?? ""] ?? failed?.name ?? "a step"}` };
  const notReached = "Not reached";
  const drift = n.drift_alarm;
  return (
    <div className="k-card t-ice" style={{ padding: 22, gridColumn: "1 / -1" }}>
      <SectionTitle eyebrow={`Nightly run · ${new Date(t0).toLocaleDateString("en-CA", { dateStyle: "medium" })}`} title="Last nightly pipeline run" />
      <Flex gap="2" wrap="wrap" mb="4">
        <Badge tone={status.tone} label="Run" value={status.value} />
        <Badge tone={n.gate == null ? "idle" : n.gate === "pass" ? "ok" : "bad"} label="Quality gate" value={n.gate == null ? notReached : n.gate === "pass" ? "Passed" : "Blocked"} />
        <Badge
          tone={n.parity == null ? "idle" : n.parity.passed ? "ok" : "bad"}
          label="Parity"
          value={
            n.parity == null
              ? notReached
              : n.parity.mismatch_rate == null
                ? n.parity.passed
                  ? "Passed"
                  : "Failed"
                : `${(n.parity.mismatch_rate * 100).toFixed(4)}% of cells differ`
          }
        />
        <Badge
          tone={drift == null ? "idle" : drift.length ? "bad" : "ok"}
          label="Drift alarm"
          value={drift == null ? notReached : drift.length ? `${drift.length} model input${drift.length > 1 ? "s" : ""} moved: ${drift.join(", ").replace(/_/g, " ")}` : "None since last night"}
        />
      </Flex>
      <div className="k-beat" role="img" aria-label={`Nightly run: ${n.steps.length} of ${rows.length} steps ran; ${status.value}.`}>
        {rows.map((s, i) => {
          const left = s.start ? ((Date.parse(s.start) - t0) / span) * 100 : 0;
          const width = Math.min(Math.max(0.6, ((s.seconds * 1000) / span) * 100), 100 - left);
          const live = running && s.start == null && i === n.steps.length;
          return (
            <div key={s.name} className="k-beat-row" data-idle={s.start == null}>
              <Text size="1" truncate>
                {STEP[s.name] ?? s.name}
              </Text>
              <div className="k-act-track k-beat-track">
                {s.start && (
                  <motion.span
                    className="k-beat-bar"
                    data-bad={s.exit !== 0}
                    title={`${STEP[s.name] ?? s.name}: started ${clock(Date.parse(s.start))}, ${took(s.seconds)}, exit ${s.exit}`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    initial={calm ? false : { scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ delay: calm ? 0 : i * 0.12, duration: 0.5, ease: "easeOut" }}
                  />
                )}
                {live && <span className="k-beat-live" />}
              </div>
              <Text size="1" color="gray" align="right" className="tabular">
                {s.start ? (s.exit === 0 ? took(s.seconds) : `Exit ${s.exit}`) : live ? "Running" : "Not run"}
              </Text>
            </div>
          );
        })}
        <div className="k-beat-row">
          <span />
          <Flex justify="between">
            <Text size="1" color="gray" className="tabular">
              {clock(t0)}
            </Text>
            <Text size="1" color="gray" className="tabular">
              {clock(end)}
            </Text>
          </Flex>
          <span />
        </div>
      </div>
    </div>
  );
}

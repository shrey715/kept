"use client";

import { Flex, Text } from "@radix-ui/themes";
import { motion } from "motion/react";
import { useLayoutEffect, useRef, useState } from "react";
import { money, type CaseStory } from "@/lib/api";
import { SectionTitle } from "./page-header";

type Promise_ = CaseStory["promises"][number];
type Tip = {
  x: number;
  y: number;
  below: boolean;
  title: string;
  lines: string[];
};

const DAY = 864e5;
/** Days since the epoch from "YYYY-MM-DD…", read as a calendar date (no time zone shifts). */
const day = (s: string) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10)) / DAY;
const fmtDay = (d: number) =>
  new Date(d * DAY).toLocaleDateString("en-CA", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

const CHANNEL: Record<string, string> = {
  call: "Calls",
  sms: "SMS",
  email: "Email",
  letter: "Letters",
  system: "System",
  ivr: "IVR",
  push: "App",
  chat: "Chat",
};
const STATUS: Record<string, string> = {
  kept: "Kept",
  partially_kept: "Partly kept",
  broken: "Broken",
  open: "Open",
  cancelled: "Cancelled",
};

const GUTTER = 92; // lane labels
const LANE = 30;
const DPD_H = 54;
const AXIS = 22;
const PX_PER_DAY = 3; // below this the timeline scrolls inside its card instead of squeezing

/** "3 days before payday", "on payday": how a promise's due date sat against the customer's recorded paydays. */
export function paydayPhrase(d: number | null | undefined) {
  if (d == null) return "No recorded payday within 40 days";
  if (d === 0) return "Due on a recorded payday";
  return d < 0 ? `Due ${-d} day${d === -1 ? "" : "s"} before the next recorded payday` : `Due ${d} day${d === 1 ? "" : "s"} after the last recorded payday`;
}

/** The case on one swim-lane chart: contacts by channel, promises, payments and notes over the same days, days past due
 * underneath and the customer's paydays as vertical ticks. Hover or focus a mark for its detail. */
export function StoryTimeline({ s }: { s: CaseStory }) {
  const wrap = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [tip, setTip] = useState<Tip | null>(null);
  const [focus, setFocus] = useState<Promise_ | null>(null);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const start = day(s.start);
  const span = Math.max(day(s.end) - start, 1);
  const W = Math.max(width, GUTTER + span * PX_PER_DAY);
  const plot = W - GUTTER - 12;
  const x = (d: number) => GUTTER + ((d - start) / span) * plot;

  // contact lanes: the three busiest channels, the rest under "Other"
  const counts = new Map<string, number>();
  for (const c of s.contacts) counts.set(c.channel, (counts.get(c.channel) ?? 0) + 1);
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  const own = ranked.length <= 4 ? ranked : ranked.slice(0, 3);
  const laneOf = (ch: string) => (own.includes(ch) ? ch : "other");
  const contactLanes = ranked.length > 4 ? [...own, "other"] : own;
  const lanes = [
    ...contactLanes.map((k) => ({
      key: `c:${k}`,
      label: k === "other" ? "Other contact" : (CHANNEL[k] ?? k),
    })),
    { key: "promises", label: "Promises" },
    { key: "payments", label: "Payments" },
    { key: "notes", label: "Notes" },
  ];
  const laneY = (key: string) => AXIS + lanes.findIndex((l) => l.key === key) * LANE + LANE / 2;
  const lanesBottom = AXIS + lanes.length * LANE;
  const H = lanesBottom + DPD_H + 8;

  // months along the top; every third month on a long case
  const months: number[] = [];
  const first = new Date(start * DAY);
  const step = span > 540 ? 3 : 1;
  for (
    let m = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1));
    m.getTime() / DAY <= start + span;
    m = new Date(Date.UTC(m.getUTCFullYear(), m.getUTCMonth() + step, 1))
  )
    months.push(m.getTime() / DAY);

  const dpd = s.contacts.filter((c) => c.dpd != null).map((c) => ({ d: day(c.at), v: c.dpd as number }));
  const maxDpd = Math.max(...dpd.map((p) => p.v), 1);
  const dy = (v: number) => lanesBottom + DPD_H - (v / maxDpd) * (DPD_H - 10);
  const dpdPath = dpd.length
    ? `M${x(dpd[0].d)},${dy(0)} ` +
      dpd.map((p, i) => `L${x(p.d)},${dy(i ? dpd[i - 1].v : p.v)} L${x(p.d)},${dy(p.v)}`).join(" ") +
      ` L${x(dpd[dpd.length - 1].d)},${dy(0)} Z`
    : "";
  const maxPay = Math.max(...s.payments.map((p) => Number(p.amount)), 1);

  const show = (e: React.MouseEvent | React.FocusEvent, title: string, lines: string[]) => {
    const r = wrap.current?.getBoundingClientRect();
    const t = (e.currentTarget as Element).getBoundingClientRect();
    if (!r) return;
    const below = t.top - r.top < 70; // near the top: open downward so the card's title stays readable
    setTip({
      x: t.left + t.width / 2 - r.left,
      y: below ? t.bottom - r.top : t.top - r.top,
      below,
      title,
      lines,
    });
  };
  const hide = () => {
    setTip(null);
    setFocus(null);
  };
  const hover = (title: string, lines: string[], p: Promise_ | null = null) => ({
    onMouseEnter: (e: React.MouseEvent) => {
      show(e, title, lines);
      setFocus(p);
    },
    onFocus: (e: React.FocusEvent) => {
      show(e, title, lines);
      setFocus(p);
    },
    onMouseLeave: hide,
    onBlur: hide,
  });

  const broken = s.promises.filter((p) => p.status === "broken");
  const nBroken = (f: (d: number) => boolean) => broken.filter((p) => p.payday_days != null && f(p.payday_days)).length;
  const brokenSplit = `Broken promises: ${nBroken((d) => d < 0)} due before a payday, ${nBroken((d) => d === 0)} on one, ${nBroken((d) => d > 0)} after one.`;
  const hardship = s.notes.filter((n) => n.hardship !== "none").length;

  return (
    <div className="k-card" style={{ padding: 22 }}>
      <SectionTitle
        eyebrow="Timeline"
        title="The case over time"
        mb="1"
        aside={
          <Flex gap="3" wrap="wrap" className="k-story-legend">
            <span>
              <i className="k-story-key kept" /> Kept
            </span>
            <span>
              <i className="k-story-key broken" /> Broken
            </span>
            <span>
              <i className="k-story-key partial" /> Partly kept
            </span>
            <span>
              <i className="k-story-key hardship" /> Hardship in a note
            </span>
            <span>
              <i className="k-story-key payday" /> Payday
            </span>
          </Flex>
        }
      />
      <Text as="p" size="1" color="gray" mb="3">
        {s.promises.length} promises, {s.contacts.length} contacts, {s.payments.length} payments and {s.notes.length} notes from {fmtDay(start)} to{" "}
        {fmtDay(start + span)}.{broken.length > 0 && ` ${brokenSplit}`}
        {hardship > 0 && ` ${hardship} note${hardship === 1 ? "" : "s"} read as possible hardship.`} Filled contact dots reached the customer.
      </Text>
      <div ref={wrap} style={{ position: "relative" }}>
        <div ref={box} className="k-story">
          {width > 0 && (
            <svg width={W} height={H} role="img" aria-label="Case timeline: contacts, promises, payments and notes by date, with days past due and paydays">
              {lanes.map((l, i) => (
                <g key={l.key}>
                  {i % 2 === 0 && <rect x={GUTTER - 6} y={AXIS + i * LANE} width={W - GUTTER} height={LANE} className="k-story-band" rx={6} />}
                  <text x={0} y={AXIS + i * LANE + LANE / 2} dominantBaseline="middle" className="k-story-lane">
                    {l.label}
                  </text>
                </g>
              ))}
              <text x={0} y={lanesBottom + DPD_H / 2} dominantBaseline="middle" className="k-story-lane">
                Days past due
              </text>
              {months.map((m) => (
                <g key={m}>
                  <line x1={x(m)} x2={x(m)} y1={AXIS - 4} y2={H - 8} className="k-story-grid" />
                  <text x={x(m) + 3} y={11} className="k-story-axis">
                    {new Date(m * DAY).toLocaleDateString("en-CA", {
                      month: "short",
                      ...(new Date(m * DAY).getUTCMonth() === 0 || m === months[0] ? { year: "numeric" } : {}),
                      timeZone: "UTC",
                    })}
                  </text>
                </g>
              ))}
              {s.paydays.map((p) => (
                <line key={p} x1={x(day(p))} x2={x(day(p))} y1={AXIS - 2} y2={H - 8} className="k-story-payday">
                  <title>Payday {fmtDay(day(p))}</title>
                </line>
              ))}

              {dpdPath && (
                <g>
                  <path d={dpdPath} className="k-story-dpd" />
                  <text x={x(dpd[dpd.length - 1].d) - 4} y={dy(dpd[dpd.length - 1].v) - 4} textAnchor="end" className="k-story-axis">
                    {dpd[dpd.length - 1].v} days
                  </text>
                </g>
              )}

              <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
                {s.contacts.map((c, i) => (
                  <circle
                    key={i}
                    cx={x(day(c.at))}
                    cy={laneY(`c:${laneOf(c.channel)}`)}
                    r={4}
                    className="k-story-contact"
                    data-reached={c.reached}
                    {...hover(`${CHANNEL[c.channel] ?? c.channel} · ${fmtDay(day(c.at))}`, [
                      c.reached ? "Reached the customer" : "Did not reach the customer",
                      ...(c.dpd != null ? [`${c.dpd} days past due`] : []),
                    ])}
                  />
                ))}

                {focus?.payday_days != null && <PaydayBracket x1={x(day(focus.due))} x2={x(day(focus.due) - focus.payday_days)} y={laneY("promises") - 11} />}
                {s.promises.map((p, i) => {
                  const made = day(p.made);
                  const due = day(p.due);
                  const y = laneY("promises");
                  const lines = [
                    `${money(p.amount, true)} due ${fmtDay(due)}, made ${fmtDay(made)}`,
                    ...(p.paid && Number(p.paid) > 0 ? [`Paid ${money(p.paid, true)}${p.paid_date ? ` on ${fmtDay(day(p.paid_date))}` : ""}`] : []),
                    paydayPhrase(p.payday_days),
                  ];
                  return (
                    <g
                      key={i}
                      tabIndex={0}
                      className="k-story-promise"
                      data-status={p.status}
                      {...hover(`Promise ${(STATUS[p.status] ?? p.status).toLowerCase()}`, lines, p)}
                    >
                      <line x1={x(made)} x2={x(due)} y1={y} y2={y} />
                      <PromiseMark cx={x(due)} cy={y} status={p.status} />
                    </g>
                  );
                })}

                {s.payments.map((p, i) => {
                  const h = 4 + (Number(p.amount) / maxPay) * (LANE - 10);
                  const y = laneY("payments") + (LANE - 10) / 2;
                  return (
                    <rect
                      key={i}
                      x={x(day(p.on)) - 2.5}
                      y={y - h}
                      width={5}
                      height={h}
                      rx={2}
                      className="k-story-pay"
                      data-promise={p.against_promise}
                      {...hover(`Payment · ${fmtDay(day(p.on))}`, [
                        money(p.amount, true),
                        p.against_promise ? "Against a promise" : "Not matched to a promise",
                      ])}
                    />
                  );
                })}

                {s.notes.map((n, i) => {
                  const hard = n.hardship !== "none";
                  const lines = [
                    ...(hard ? [`Possible hardship${n.reason ? `: ${n.reason.replaceAll("_", " ")}` : ""}`] : []),
                    ...(n.quote ? [`Quote: “${n.quote}”`] : []),
                    ...(n.text ? [n.text.length >= 280 ? `${n.text}…` : n.text] : []),
                  ];
                  const props = hover(`${n.source === "transcript" ? "Call transcript" : "Note"} · ${fmtDay(day(n.at))}`, lines);
                  const cx = x(day(n.at));
                  const cy = laneY("notes");
                  return n.source === "transcript" ? (
                    <rect key={i} x={cx - 4.5} y={cy - 4.5} width={9} height={9} rx={2} tabIndex={0} className="k-story-note" data-hardship={hard} {...props} />
                  ) : (
                    <circle key={i} cx={cx} cy={cy} r={hard ? 5.5 : 4} tabIndex={0} className="k-story-note" data-hardship={hard} {...props} />
                  );
                })}
              </motion.g>
            </svg>
          )}
        </div>
        {tip && (
          <div
            className="k-story-tip"
            data-below={tip.below}
            style={{
              left: Math.min(Math.max(tip.x, 140), width - 140),
              top: tip.y,
            }}
            role="status"
          >
            <b>{tip.title}</b>
            {tip.lines.map((l, i) => (
              <span key={i}>{l}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Kept: a filled dot. Broken: a cross. Partly kept: a half-filled dot. Open or cancelled: a ring. */
function PromiseMark({ cx, cy, status }: { cx: number; cy: number; status: string }) {
  if (status === "broken")
    return (
      <g className="k-story-mark">
        <circle cx={cx} cy={cy} r={7} className="k-story-hit" />
        <path d={`M${cx - 4.5},${cy - 4.5} L${cx + 4.5},${cy + 4.5} M${cx + 4.5},${cy - 4.5} L${cx - 4.5},${cy + 4.5}`} />
      </g>
    );
  if (status === "partially_kept")
    return (
      <g className="k-story-mark">
        <circle cx={cx} cy={cy} r={5.5} className="k-story-ring" />
        <path d={`M${cx},${cy - 5.5} A5.5,5.5 0 0 1 ${cx},${cy + 5.5} Z`} />
      </g>
    );
  return <circle cx={cx} cy={cy} r={5.5} className="k-story-mark" />;
}

/** On hover, the gap between a promise's due date and the payday it sat against, as a bracket with its length. */
function PaydayBracket({ x1, x2, y }: { x1: number; x2: number; y: number }) {
  if (Math.abs(x2 - x1) < 1) return null;
  const [a, b] = x1 < x2 ? [x1, x2] : [x2, x1];
  return <path d={`M${a},${y + 4} L${a},${y} L${b},${y} L${b},${y + 4}`} className="k-story-bracket" />;
}

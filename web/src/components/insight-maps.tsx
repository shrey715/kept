"use client";

// The two flat maps on the Insights page: calling hours by province now (#103) and financial stress by
// province over the last 12 month-ends (#112). Plain SVG on the projected provinces (lib/geo).
import { PauseIcon, PlayIcon, ResetIcon } from "@radix-ui/react-icons";
import { Box, Flex, Grid, Text } from "@radix-ui/themes";
import { useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { ACTION_LABEL, money, type Action, type CallingHours, type CollectionsMap, type StressMap, type UpliftLandscape } from "@/lib/api";
import { useServerClock } from "@/lib/clock";
import { anchor, bounds, loadProvinces, localTime, project, svgPath, type Province } from "@/lib/geo";

const W = 800;
const PAD = 12;
const ET = "America/Toronto";
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const pct = (v: number, d = 0) => `${(v * 100).toFixed(d)}%`;
const n = (v: number) => v.toLocaleString("en-CA");

/** The provinces and a fit to an 800-wide viewBox (y down). */
function useMap() {
  const [shapes, setShapes] = useState<Province[] | null>(null);
  useEffect(() => {
    let live = true;
    loadProvinces().then((s) => live && setShapes(s), () => undefined);
    return () => {
      live = false;
    };
  }, []);
  return useMemo(() => {
    if (!shapes) return null;
    const [x0, y0, x1, y1] = bounds(shapes);
    const k = (W - 2 * PAD) / (x1 - x0);
    const H = Math.round((y1 - y0) * k + 2 * PAD);
    const fit = (x: number, y: number): [number, number] => [PAD + (x - x0) * k, PAD + (y1 - y) * k];
    return {
      H,
      fit,
      provinces: shapes.map((p) => ({ ...p, d: svgPath(p, fit), at: fit(...anchor(p)) })),
    };
  }, [shapes]);
}

// ------------------------------------------------------------------ the shared map: one look for both flat maps
type Tip = { x: number; y: number; w: number; h: number };

/** Where a 272-wide tooltip goes: beside the pointer, flipped left or above when it would leave the map. */
function tipAt(t: Tip, width = 272, height = 160): React.CSSProperties {
  const left = t.x + 18 + width > t.w ? t.x - 18 - width : t.x + 18;
  const top = t.y + 12 + height > t.h ? t.y - 12 - height : t.y + 12;
  return { left: Math.max(8, left), top: Math.max(8, top) };
}

/** A province map with the house behaviour: the hovered province lifts and the rest dim, a card follows the
 * pointer, the map tilts slightly toward it, and every province is labelled and reachable by keyboard. */
function LiveMap({
  label,
  fill,
  known,
  hover,
  setHover,
  tip,
}: {
  label: string;
  fill: (code: string) => string;
  known: (code: string) => boolean;
  hover: string | null;
  setHover: (code: string | null) => void;
  tip: (code: string, name: string) => React.ReactNode;
}) {
  const map = useMap();
  const calm = useReducedMotion() ?? false;
  const wrap = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState<Tip | null>(null);
  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = wrap.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    if (!calm) {
      el.style.setProperty("--rx", `${(y / r.height - 0.5) * -4}deg`);
      el.style.setProperty("--ry", `${(x / r.width - 0.5) * 5}deg`);
    }
    setAt({ x, y, w: r.width, h: r.height });
  };
  const onLeave = () => {
    wrap.current?.style.setProperty("--rx", "0deg");
    wrap.current?.style.setProperty("--ry", "0deg");
    setHover(null);
    setAt(null);
  };
  const name = hover ? map?.provinces.find((p) => p.code === hover)?.name : undefined;
  return (
    <div ref={wrap} className="k-live-map" onPointerMove={onMove} onPointerLeave={onLeave}>
      {map ? (
        <svg viewBox={`0 0 ${W} ${map.H}`} className="k-geo k-live-svg" role="img" aria-label={label}>
          <defs>
            <pattern id="k-geo-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="var(--k-card)" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--k-hatch)" strokeWidth="2" />
            </pattern>
          </defs>
          {map.provinces.map((p) => (
            <path
              key={p.code}
              d={p.d}
              fill={known(p.code) ? fill(p.code) : "url(#k-geo-hatch)"}
              className="k-live-shape"
              data-hover={hover === p.code}
              data-dim={hover !== null && hover !== p.code}
              onPointerEnter={() => setHover(p.code)}
              tabIndex={known(p.code) ? 0 : -1}
              onFocus={() => setHover(p.code)}
              onBlur={() => setHover(null)}
              aria-label={p.name}
            />
          ))}
          <g pointerEvents="none">
            {map.provinces.map((p) =>
              known(p.code) ? (
                <text key={p.code} x={p.at[0]} y={p.at[1] + 4} className="k-live-label" data-hover={hover === p.code}>
                  {p.code}
                </text>
              ) : null,
            )}
          </g>
        </svg>
      ) : (
        <div className="k-geo-empty" />
      )}
      {hover && name && at && (
        <div className="k-live-tip" style={tipAt(at)}>
          {tip(hover, name)}
        </div>
      )}
    </div>
  );
}

/** A row of the list beside a map: code, a value, and a strip of cells (hours or months). Hover links to the map. */
function SideRow({ code, value, dim, hover, setHover, children }: { code: string; value: string; dim?: boolean; hover: string | null; setHover: (c: string | null) => void; children: React.ReactNode }) {
  return (
    <div className="k-live-row" data-dim={dim} data-hover={hover === code} onPointerEnter={() => setHover(code)} onPointerLeave={() => setHover(null)}>
      <span className="code">{code}</span>
      <span className="time tabular">{value}</span>
      {children}
    </div>
  );
}

/** Play/pause plus a scrubber, the same control for hours and months. */
function Scrubber({ playing, onPlay, onReset, children }: { playing: boolean; onPlay: () => void; onReset?: () => void; children: React.ReactNode }) {
  return (
    <Flex align="center" gap="2" mt="3" wrap="wrap">
      <button className="k-round-btn" style={{ width: 34, height: 34 }} onClick={onPlay} aria-label={playing ? "Pause" : "Play"} title={playing ? "Pause" : "Play"}>
        {playing ? <PauseIcon /> : <PlayIcon />}
      </button>
      {onReset && (
        <button className="k-round-btn" style={{ width: 34, height: 34 }} onClick={onReset} aria-label="Back to now" title="Back to now">
          <ResetIcon />
        </button>
      )}
      {children}
    </Flex>
  );
}

function Layers<T extends string>({ value, options, onChange, label }: { value: T; options: readonly (readonly [T, string])[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="k-tabs" role="tablist" aria-label={label}>
      {options.map(([k, text]) => (
        <button key={k} role="tab" aria-selected={value === k} className="k-tab" data-active={value === k} style={{ height: 30 }} onClick={() => onChange(k)}>
          {text}
        </button>
      ))}
    </div>
  );
}

const ramp = (share: number) => `color-mix(in oklab, var(--k-red) ${Math.round(8 + 82 * Math.max(0, Math.min(1, share)))}%, var(--k-card))`;

// ------------------------------------------------------------------ calling hours (#103)
const EAST_TO_WEST = ["NL", "NS", "PE", "NB", "QC", "NU", "ON", "MB", "SK", "AB", "NT", "BC", "YT"];
type Layer = "hours" | "heat";

/** Minutes since midnight Eastern, and the instant of that midnight. */
function etDay(t: number) {
  const m = localTime(t, ET).minutes;
  return { minutes: m, midnight: Math.floor(t / 60000) * 60000 - m * 60000 };
}

const toMin = (x: string) => Number(x.slice(0, 2)) * 60 + Number(x.slice(3, 5));
const span = (m: number) => (m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min` : `${m} min`);

export function CallingHoursMap({ data }: { data: CallingHours }) {
  const calm = useReducedMotion() ?? false;
  const clock = useServerClock().now; // the app's clock: business hours on the demo server
  const [boot] = useState(() => Date.now());
  const [picked, setPicked] = useState<number | null>(null); // null: follow the clock
  const [playing, setPlaying] = useState(false);
  const [layer, setLayer] = useState<Layer>("hours");
  const [hover, setHover] = useState<string | null>(null);
  const t = picked ?? clock?.getTime() ?? boot;
  const live = picked === null;

  useEffect(() => {
    if (!playing) return;
    // reduced motion: hour steps, slowly; otherwise ten minutes every 80 ms
    const step = (x: number) => (etDay(x + 1).minutes >= 1430 ? etDay(x).midnight : x + (calm ? 60 : 10) * 60000);
    const id = setInterval(() => setPicked((x) => (x == null ? x : step(x))), calm ? 700 : 80);
    return () => clearInterval(id);
  }, [playing, calm]);

  const bank = useMemo(() => {
    const at = new Map<string, number>();
    const total = new Map<string, number>();
    let peak = 1;
    for (const b of data.bank) {
      at.set(`${b.province}|${b.day}|${b.hour}`, b.contacts);
      total.set(b.province, (total.get(b.province) ?? 0) + b.contacts);
      peak = Math.max(peak, b.contacts);
    }
    return { at, total, peak };
  }, [data.bank]);

  const rows = data.provinces.map((p) => {
    const lt = localTime(t, p.time_zone);
    const [s, e] = [toMin(p.start), toMin(p.end)];
    const inside = lt.minutes >= s && lt.minutes < e;
    const share = !inside ? 0 : lt.day === "Sun" ? p.sunday_share : 1; // permission_gate: no Sunday unless allowed
    const status = share >= 0.999 ? "open" : share > 0 ? "partial" : "closed";
    const change = inside ? `closes in ${span(e - lt.minutes)}` : `opens in ${span((s - lt.minutes + 1440) % 1440)}`;
    const rate = ((bank.total.get(p.province) ?? 0) / Math.max(1, p.customers)) * 1000; // per 1,000 customers
    return { ...p, lt, s, e, share, status, change, rate, now: bank.at.get(`${p.province}|${lt.day}|${Math.floor(lt.minutes / 60)}`) ?? 0 };
  });
  const by = new Map(rows.map((r) => [r.province, r]));
  const maxRate = Math.max(0.001, ...rows.map((r) => r.rate));
  const open = rows.filter((r) => r.status !== "closed").length;
  const nowContacts = rows.reduce((sum, r) => sum + r.now, 0);
  const { minutes, midnight } = etDay(t);
  const etLabel = localTime(t, ET).label;
  const today = localTime(t, ET).day;
  const scrub = (next: number) => setPicked(next);

  const fill = (code: string) => {
    const r = by.get(code)!;
    if (layer === "heat") return ramp(Math.sqrt(r.rate / maxRate));
    return r.status === "open" ? "var(--k-open)" : r.status === "partial" ? `color-mix(in oklab, var(--k-open) ${Math.round(r.share * 100)}%, var(--k-closed))` : "var(--k-closed)";
  };

  return (
    <Box>
      <Grid columns={{ initial: "1", md: "3" }} gap="3" mb="4">
        <Stat tint="mint" label="Provinces open now" value={`${open} of ${rows.length}`} sub={`${etLabel} Eastern${live ? " · live" : ""}`} />
        <Stat tint="rose" label="Bank: contacts outside permitted hours" value={n(data.bank_contacts)} sub={`${n(data.bank_cases)} cases, ${pct(data.bank_cases / Math.max(1, data.cases), 1)} of all`} />
        <Stat tint="ice" label="Kept: cards outside permitted hours" value={n(data.kept_outside)} sub={`of ${n(data.kept_cards)} contact cards tonight`} />
      </Grid>

      <Grid columns={{ initial: "1", md: "3fr 1.2fr" }} gap="4" align="start">
        <Box>
          <Flex justify="between" align="center" mb="2" gap="2" wrap="wrap">
            <Layers
              label="Map layer"
              value={layer}
              onChange={setLayer}
              options={[
                ["hours", "Calling hours"],
                ["heat", "Out-of-hours contacts"],
              ]}
            />
            <span className="k-live-clock tabular" data-live={live}>
              <span className="dot" aria-hidden />
              {etLabel} Eastern
            </span>
          </Flex>
          <LiveMap
            label={`Calling hours by province at ${etLabel} Eastern: ${open} of ${rows.length} open`}
            fill={fill}
            known={(c) => by.has(c)}
            hover={hover}
            setHover={setHover}
            tip={(code, name) => {
              const r = by.get(code)!;
              return (
                <>
                  <div className="k-live-tip-head">
                    <b>{name}</b>
                    <span className="k-geo-pill" data-status={r.status}>
                      {r.status === "open" ? "Open" : r.status === "partial" ? `${pct(r.share)} open` : "Closed"}
                    </span>
                  </div>
                  <div className="k-live-tip-row tabular">
                    {r.lt.label} local · {r.change}
                  </div>
                  <div className="k-live-tip-row">
                    {n(r.customers)} customers · {n(bank.total.get(code) ?? 0)} bank contacts outside hours ({r.rate.toFixed(1)} per 1,000)
                  </div>
                  <HourStrip r={r} at={bank.at} peak={bank.peak} big />
                </>
              );
            }}
          />
          <Scrubber playing={playing} onPlay={() => (setPicked(t), setPlaying((x) => !x))} onReset={() => (setPlaying(false), setPicked(null))}>
            <div className="k-tabs">
              {DAYS.map((d, i) => (
                <button key={d} className="k-tab" data-active={d === today} style={{ height: 30, padding: "0 10px" }} onClick={() => scrub(t + (i - DAYS.indexOf(today)) * 86_400_000)}>
                  {d}
                </button>
              ))}
            </div>
          </Scrubber>
          <input type="range" className="k-scrub" min={0} max={1435} step={5} value={minutes} onChange={(e) => scrub(midnight + Number(e.target.value) * 60000)} aria-label="Time of day, Eastern" aria-valuetext={`${etLabel} Eastern`} />
          <Flex justify="between">
            {["00:00", "06:00", "12:00", "18:00", "24:00"].map((x) => (
              <Text key={x} size="1" color="gray" className="tabular">
                {x}
              </Text>
            ))}
          </Flex>
          <Flex gap="4" mt="2" wrap="wrap" align="center">
            {layer === "hours" ? (
              <>
                <Key swatch="var(--k-open)" label="Open: 07:00 to 21:00 local" />
                <Key swatch="color-mix(in oklab, var(--k-open) 50%, var(--k-closed))" label="Sunday: open for customers who allow it" />
                <Key swatch="var(--k-closed)" label="Closed" />
              </>
            ) : (
              <span className="k-live-heatkey">
                0 <i /> {maxRate.toFixed(1)} bank contacts outside hours per 1,000 customers
              </span>
            )}
          </Flex>
        </Box>

        <Box className="k-live-side">
          <Flex justify="between" mb="2">
            <Text size="1" color="gray">
              Province · local time
            </Text>
            <Text size="1" color="gray">
              Today, 00 to 24 h
            </Text>
          </Flex>
          <Flex direction="column" gap="1">
            {[...rows]
              .sort((x, y) => EAST_TO_WEST.indexOf(x.province) - EAST_TO_WEST.indexOf(y.province))
              .map((r) => (
                <SideRow key={r.province} code={r.province} value={r.lt.label.slice(4)} dim={r.status === "closed"} hover={hover} setHover={setHover}>
                  <HourStrip r={r} at={bank.at} peak={bank.peak} />
                </SideRow>
              ))}
          </Flex>
          <Flex gap="3" mt="2" wrap="wrap">
            <Key swatch="var(--k-open)" label="Calling window" />
            <Key swatch={ramp(0.6)} label="Bank contacts outside it" />
          </Flex>
          <Text as="p" size="1" color="gray" mt="3">
            At this local hour and weekday the bank&apos;s history shows <b>{n(nowContacts)}</b> contacts outside permitted hours. Kept proposes a contact only inside the customer&apos;s window and checks it again at release.
          </Text>
        </Box>
      </Grid>
    </Box>
  );
}

/** One province's day as 24 hourly cells: green inside the calling window, red by the bank's contacts outside
 * it at that local hour on this weekday; the current hour is outlined. */
function HourStrip({ r, at, peak, big = false }: { r: { province: string; lt: { day: string; minutes: number }; s: number; e: number }; at: Map<string, number>; peak: number; big?: boolean }) {
  const hourNow = Math.floor(r.lt.minutes / 60);
  return (
    <span className="k-hstrip" data-big={big} aria-hidden>
      {Array.from({ length: 24 }, (_, hr) => {
        const c = at.get(`${r.province}|${r.lt.day}|${hr}`) ?? 0;
        const open = hr * 60 >= r.s && hr * 60 < r.e;
        const style = c ? { background: ramp(0.25 + 0.75 * Math.sqrt(c / peak)) } : open ? { background: "var(--k-open)" } : undefined;
        return <i key={hr} style={style} data-now={hr === hourNow} />;
      })}
    </span>
  );
}

function Stat({ tint, label, value, sub }: { tint: string; label: string; value: string; sub: string }) {
  return (
    <div className={`k-card t-${tint}`} style={{ padding: "14px 16px" }}>
      <Text as="div" size="1" weight="medium">
        {label}
      </Text>
      <div style={{ fontSize: 28, fontWeight: 400, letterSpacing: "-0.03em", lineHeight: 1.15, marginTop: 4 }} className="tabular">
        {value}
      </div>
      <Text as="div" size="1" color="gray">
        {sub}
      </Text>
    </div>
  );
}

function Key({ swatch, label }: { swatch: string; label: string }) {
  return (
    <Flex align="center" gap="2">
      <span className="k-geo-swatch" style={{ background: swatch }} />
      <Text size="1" color="gray">
        {label}
      </Text>
    </Flex>
  );
}

// ------------------------------------------------------------------ stress map (#112)
type Metric = "falling_cash_flow" | "payroll_delay" | "hardship";
const METRICS: Record<Metric, { label: string; what: string; base: (c: StressMap["cells"][number]) => number; baseLabel: string }> = {
  falling_cash_flow: { label: "Falling cash flow", what: "Net cash flow lower than at the month-end before", base: (c) => c.cash_flow_base, baseLabel: "customers with a deposit account" },
  payroll_delay: { label: "Payroll delay", what: "Employer pay arrived more than 5 days after it was due", base: (c) => c.payroll_base, baseLabel: "customers paid by an employer that month" },
  hardship: { label: "Hardship flag", what: "A hardship-flagged collections case open at the month-end", base: (c) => c.customers, baseLabel: "customers" },
};
const monthLabel = (d: string) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-CA", { month: "short", year: "numeric", timeZone: "UTC" });
const monthShort = (d: string) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-CA", { month: "short", timeZone: "UTC" });

export function StressMapView({ data }: { data: StressMap }) {
  const calm = useReducedMotion() ?? false;
  const [metric, setMetric] = useState<Metric>("hardship");
  const [i, setI] = useState(data.months.length - 1);
  const [playing, setPlaying] = useState(false);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setI((x) => (x + 1) % data.months.length), calm ? 1400 : 700);
    return () => clearInterval(id);
  }, [playing, calm, data.months.length]);

  const month = data.months[i];
  const m = METRICS[metric];
  const vals = data.cells.map((c) => c[metric]).filter((v): v is number => v != null);
  const [lo, hi] = [Math.min(...vals, 0), Math.max(...vals, 0.0001)];
  const share = (v: number) => (v - lo) / (hi - lo || 1);
  const cell = useMemo(() => new Map(data.cells.map((c) => [`${c.province}|${c.month}`, c])), [data.cells]);
  const now = new Map(data.cells.filter((c) => c.month === month).map((c) => [c.province, c]));
  const ranked = [...now.values()].sort((a, b) => (b[metric] ?? -1) - (a[metric] ?? -1));
  const prev = i > 0 ? data.months[i - 1] : null;
  const national = (() => {
    const cs = [...now.values()].filter((c) => c[metric] != null);
    const base = cs.reduce((sum, c) => sum + m.base(c), 0);
    return base ? cs.reduce((sum, c) => sum + (c[metric] ?? 0) * m.base(c), 0) / base : null;
  })();
  const top = ranked.find((c) => c[metric] != null);

  const strip = (code: string, big = false) => (
    <span className="k-hstrip" data-big={big} style={{ gridTemplateColumns: `repeat(${data.months.length}, 1fr)` }} aria-hidden>
      {data.months.map((mo, k) => {
        const v = cell.get(`${code}|${mo}`)?.[metric];
        return <i key={mo} style={v != null ? { background: ramp(share(v)) } : undefined} data-now={k === i} />;
      })}
    </span>
  );

  return (
    <Box>
      <Grid columns={{ initial: "1", md: "3" }} gap="3" mb="4">
        <Stat tint="rose" label={`${m.label}, all provinces`} value={national == null ? "—" : pct(national, 1)} sub={`${monthLabel(month)} · share of ${m.baseLabel}`} />
        <Stat tint="butter" label="Highest province" value={top ? `${top.province} · ${pct(top[metric]!, 1)}` : "—"} sub={top ? `${n(m.base(top))} ${m.baseLabel}` : "No province with enough customers"} />
        <Stat tint="ice" label="Months shown" value={`${data.months.length}`} sub={`${monthLabel(data.months[0])} to ${monthLabel(data.months[data.months.length - 1])}`} />
      </Grid>

      <Grid columns={{ initial: "1", md: "3fr 1.2fr" }} gap="4" align="start">
        <Box>
          <Flex justify="between" align="center" mb="2" gap="2" wrap="wrap">
            <Layers label="Measure" value={metric} onChange={setMetric} options={(Object.keys(METRICS) as Metric[]).map((k) => [k, METRICS[k].label] as const)} />
            <Text size="1" color="gray">
              {m.what}
            </Text>
          </Flex>
          <LiveMap
            label={`${m.label} by province, ${monthLabel(month)}`}
            fill={(code) => {
              const v = now.get(code)?.[metric];
              return v == null ? "url(#k-geo-hatch)" : ramp(share(v));
            }}
            known={(c) => now.has(c)}
            hover={hover}
            setHover={setHover}
            tip={(code, name) => {
              const c = now.get(code)!;
              const v = c[metric];
              const before = prev ? cell.get(`${code}|${prev}`)?.[metric] : null;
              return (
                <>
                  <div className="k-live-tip-head">
                    <b>{name}</b>
                    <span className="tabular">{v == null ? "—" : pct(v, 1)}</span>
                  </div>
                  <div className="k-live-tip-row">
                    {v == null ? "Too few customers, or no earlier month to compare" : `of ${n(m.base(c))} ${m.baseLabel}, ${monthLabel(month)}`}
                  </div>
                  {v != null && before != null && (
                    <div className="k-live-tip-row tabular">
                      {v >= before ? "Up" : "Down"} {Math.abs((v - before) * 100).toFixed(1)} points from {monthShort(prev!)}
                    </div>
                  )}
                  {strip(code, true)}
                </>
              );
            }}
          />
          <Scrubber playing={playing} onPlay={() => setPlaying((x) => !x)}>
            <Text size="2" weight="medium" className="tabular">
              {monthLabel(month)}
            </Text>
          </Scrubber>
          <input type="range" className="k-scrub" min={0} max={data.months.length - 1} value={i} onChange={(e) => (setPlaying(false), setI(Number(e.target.value)))} aria-label="Month-end" aria-valuetext={monthLabel(month)} />
          <Flex justify="between">
            {[data.months[0], data.months[Math.floor(data.months.length / 2)], data.months[data.months.length - 1]].map((x) => (
              <Text key={x} size="1" color="gray" className="tabular">
                {monthLabel(x)}
              </Text>
            ))}
          </Flex>
          <Flex gap="4" mt="2" wrap="wrap" align="center">
            <span className="k-live-heatkey">
              {pct(lo)} <i /> {pct(hi)} {m.label.toLowerCase()}
            </span>
            <Key swatch="repeating-linear-gradient(45deg, var(--k-hatch) 0 2px, var(--k-card) 2px 6px)" label="Fewer than 50 customers, or no earlier month" />
          </Flex>
        </Box>

        <Box className="k-live-side">
          <Flex justify="between" mb="2">
            <Text size="1" color="gray">
              Province · {monthShort(month)}
            </Text>
            <Text size="1" color="gray">
              Last {data.months.length} month-ends
            </Text>
          </Flex>
          <Flex direction="column" gap="1">
            {ranked.map((c) => (
              <SideRow key={c.province} code={c.province} value={c[metric] == null ? "—" : pct(c[metric]!, 1)} hover={hover} setHover={setHover}>
                {strip(c.province)}
              </SideRow>
            ))}
          </Flex>
          <Text as="p" size="1" color="gray" mt="3">
            Customers in tonight&apos;s portfolio at each month-end; provinces with fewer than 50 are left out.
          </Text>
        </Box>
      </Grid>
    </Box>
  );
}

// ------------------------------------------------------------------ the uplift model (#109)
export const ACTION_COLOR: Record<string, string> = {
  call: "#e5484d",
  email: "#3e63dd",
  sms_payment_link: "#12a594",
  push: "#8e4ec6",
  hardship_review: "#f76b15",
  promise_request: "#d6a400",
  payment_plan: "#46a758",
  none: "#8d8d86",
};
const actionName = (a: string) => (a === "none" ? "No action" : (ACTION_LABEL[a as Action] ?? a));
/** Diverging: green where a call adds to the chance of payment, red where it takes away, card colour at zero. */
const diverge = (u: number, big: number) => {
  const k = Math.round(10 + 80 * Math.sqrt(Math.min(1, Math.abs(u) / big)));
  return Math.abs(u) < 0.0005 ? "var(--k-card)" : `color-mix(in oklab, ${u > 0 ? "#2f8f57" : "var(--k-red)"} ${k}%, var(--k-card))`;
};
const pts = (u: number) => `${u >= 0 ? "+" : "−"}${Math.abs(u * 100).toFixed(1)} pts`;

/** A one-feature slice through the selected profile: the call's effect along one axis, the other held. Green above
 * zero, red below; hover reads a value, click moves the selection. */
function Slice({ title, xs, ys, sel, big, fmtX, onPick }: { title: string; xs: number[]; ys: number[]; sel: number; big: number; fmtX: (v: number) => string; onPick: (i: number) => void }) {
  const [hov, setHov] = useState<number | null>(null);
  const [Wd, Ht, P] = [360, 140, 28];
  const x = (i: number) => P + (i / Math.max(1, xs.length - 1)) * (Wd - P - 8);
  const y = (u: number) => 12 + (1 - (u + big) / (2 * big)) * (Ht - 34);
  const line = ys.map((u, i) => `${x(i)},${y(u)}`).join(" ");
  const area = (sign: 1 | -1) => `M${x(0)},${y(0)} ` + ys.map((u, i) => `L${x(i)},${y(sign > 0 ? Math.max(0, u) : Math.min(0, u))}`).join(" ") + ` L${x(ys.length - 1)},${y(0)} Z`;
  const show = hov ?? sel;
  return (
    <div className="k-slice">
      <Flex justify="between" align="baseline">
        <Text size="1" weight="medium">
          {title}
        </Text>
        <Text size="1" className="tabular" color={hov == null ? "gray" : undefined}>
          {fmtX(xs[show])}: <b>{pts(ys[show])}</b>
        </Text>
      </Flex>
      <svg viewBox={`0 0 ${Wd} ${Ht}`} className="k-slice-svg" onPointerLeave={() => setHov(null)}>
        <path d={area(1)} className="k-slice-up" />
        <path d={area(-1)} className="k-slice-down" />
        <line x1={P} x2={Wd - 8} y1={y(0)} y2={y(0)} className="k-uplift-zero" />
        <polyline points={line} className="k-uplift-curve" />
        <line x1={x(sel)} x2={x(sel)} y1={8} y2={Ht - 22} className="k-slice-sel" />
        <circle cx={x(sel)} cy={y(ys[sel])} r={4.5} className="k-slice-pin" />
        {hov != null && hov !== sel && <circle cx={x(hov)} cy={y(ys[hov])} r={3.5} className="k-uplift-curve-dot" />}
        {xs.map((_, i) => (
          <rect key={i} x={x(i) - (Wd - P) / xs.length / 2} y={0} width={(Wd - P) / xs.length} height={Ht - 20} fill="transparent" onPointerEnter={() => setHov(i)} onClick={() => onPick(i)} style={{ cursor: "pointer" }} />
        ))}
        {[0, Math.floor((xs.length - 1) / 2), xs.length - 1].map((i) => (
          <text key={i} x={x(i)} y={Ht - 6} className="k-axis-text" textAnchor={i === 0 ? "start" : i === xs.length - 1 ? "end" : "middle"}>
            {fmtX(xs[i])}
          </text>
        ))}
        <text x={P - 6} y={y(0) + 4} className="k-axis-text" textAnchor="end">
          0
        </text>
      </svg>
    </div>
  );
}

/** A what-if explorer for the uplift model: pick a customer profile on the map of the call's effect, read the effect
 * plainly, see one-feature slices through it, and where tonight's cases sit. The 3D surface one click away. */
export function UpliftExplorer({ data, surface }: { data: UpliftLandscape; surface: React.ReactNode }) {
  const [view, setView] = useState<"explore" | "surface">("explore");
  const [nx, ny] = [data.dpd.length, data.answer_rate.length];
  const big = Math.max(1e-6, ...data.uplift.flat().map(Math.abs));
  const near = (arr: number[], v: number) => arr.reduce((b, x, i) => (Math.abs(x - v) < Math.abs(arr[b] - v) ? i : b), 0);
  const [sel, setSel] = useState(() => ({ i: near(data.dpd, 60), j: near(data.answer_rate, 0.5) }));
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null);
  const [at, setAt] = useState<Tip | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [L, T, CW, CH] = [48, 10, 560, 300];
  const cw = CW / nx;
  const ch = CH / ny;
  const maxD = data.dpd[nx - 1] || 1;
  const xOf = (d: number) => L + (Math.min(d, maxD) / maxD) * CW;
  const yOf = (a: number) => T + (1 - a) * CH;
  const most = Math.max(1, ...data.groups.map((g) => g.cases));
  const total = data.groups.reduce((sum, g) => sum + g.cases, 0) || 1;
  const helped = data.groups.filter((g) => g.uplift > 0).reduce((sum, g) => sum + g.cases, 0);
  let best = { u: -Infinity, i: 0, j: 0 };
  let worst = { u: Infinity, i: 0, j: 0 };
  data.uplift.forEach((row, j) =>
    row.forEach((u, i) => {
      if (u > best.u) best = { u, i, j };
      if (u < worst.u) worst = { u, i, j };
    }),
  );
  const u = data.uplift[sel.j][sel.i];
  const [d0, a0] = [data.dpd[sel.i], data.answer_rate[sel.j]];
  // tonight's cases near the selected profile: groups within 15 days and 15 points of answer rate
  const close = data.groups.filter((g) => Math.abs(g.dpd - d0) <= 15 && Math.abs(g.answer_rate - a0) <= 0.15);
  const closeN = close.reduce((sum, g) => sum + g.cases, 0);
  const mix = Object.entries(close.reduce<Record<string, number>>((m, g) => ((m[g.action] = (m[g.action] ?? 0) + g.cases), m), {})).sort((p, q) => q[1] - p[1]);
  // distribution of tonight's cases by predicted call uplift, half-point bins
  const binW = 0.005;
  const bins = new Map<number, number>();
  for (const g of data.groups) bins.set(Math.floor(g.uplift / binW), (bins.get(Math.floor(g.uplift / binW)) ?? 0) + g.cases);
  const keys = [...bins.keys()].sort((p, q) => p - q);
  const bMax = Math.max(1, ...bins.values());
  const actions = [...new Set(data.groups.map((g) => g.action))];
  const cell = hover ? { d: data.dpd[hover.i], a: data.answer_rate[hover.j], u: data.uplift[hover.j][hover.i] } : null;
  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = wrap.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setAt({ x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height });
  };

  return (
    <Box>
      <Grid columns={{ initial: "1", md: "3" }} gap="3" mb="4">
        <Stat tint="mint" label="Tonight's cases where a call helps" value={pct(helped / total)} sub={`${n(helped)} of ${n(total)} cases with an answer rate`} />
        <Stat tint="ice" label="Largest gain from a call" value={pts(best.u)} sub={`${data.dpd[best.i]} days past due, ${pct(data.answer_rate[best.j])} answer rate`} />
        <Stat tint="rose" label="Largest loss from a call" value={pts(worst.u)} sub={`${data.dpd[worst.i]} days past due, ${pct(data.answer_rate[worst.j])} answer rate`} />
      </Grid>
      <Flex justify="between" align="center" mb="2" gap="2" wrap="wrap">
        <Layers
          label="View"
          value={view}
          onChange={setView}
          options={[
            ["explore", "Explorer"],
            ["surface", "3D surface"],
          ]}
        />
        <Text size="1" color="gray">
          Change in the chance of payment within 14 days from a call rather than waiting. Click the map to pick a profile.
        </Text>
      </Flex>
      {view === "surface" ? (
        surface
      ) : (
        <>
          <Grid columns={{ initial: "1", md: "1.55fr 1fr" }} gap="4" align="stretch">
            <div ref={wrap} className="k-live-map k-uplift" onPointerMove={onMove} onPointerLeave={() => (setHover(null), setAt(null))}>
              <svg viewBox={`0 0 ${L + CW + 8} ${T + CH + 40}`} className="k-uplift-svg" role="img" aria-label="Call uplift by days past due and answer rate">
                {data.uplift.map((row, j) =>
                  row.map((v, i) => (
                    <rect
                      key={`${i}-${j}`}
                      x={L + i * cw}
                      y={T + (ny - 1 - j) * ch}
                      width={cw + 0.5}
                      height={ch + 0.5}
                      fill={diverge(v, big)}
                      onPointerEnter={() => setHover({ i, j })}
                      onClick={() => setSel({ i, j })}
                      style={{ cursor: "pointer" }}
                    />
                  )),
                )}
                {data.groups.map((g, k) => (
                  <circle key={k} cx={xOf(g.dpd)} cy={yOf(g.answer_rate)} r={2 + 5 * Math.sqrt(g.cases / most)} className="k-uplift-dot" fill={ACTION_COLOR[g.action] ?? ACTION_COLOR.none} pointerEvents="none" />
                ))}
                {hover && (
                  <g pointerEvents="none" className="k-uplift-cross">
                    <line x1={L + (hover.i + 0.5) * cw} x2={L + (hover.i + 0.5) * cw} y1={T} y2={T + CH} />
                    <line x1={L} x2={L + CW} y1={T + (ny - 1 - hover.j + 0.5) * ch} y2={T + (ny - 1 - hover.j + 0.5) * ch} />
                  </g>
                )}
                <g pointerEvents="none" className="k-uplift-pin">
                  <line x1={L + (sel.i + 0.5) * cw} x2={L + (sel.i + 0.5) * cw} y1={T} y2={T + CH} />
                  <line x1={L} x2={L + CW} y1={T + (ny - 1 - sel.j + 0.5) * ch} y2={T + (ny - 1 - sel.j + 0.5) * ch} />
                  <circle cx={L + (sel.i + 0.5) * cw} cy={T + (ny - 1 - sel.j + 0.5) * ch} r={7} />
                </g>
                {[0, 30, 60, 90, 120, 150, 180].filter((d) => d <= maxD).map((d) => (
                  <text key={d} x={xOf(d)} y={T + CH + 16} className="k-axis-text" textAnchor={d >= maxD ? "end" : d === 0 ? "start" : "middle"}>
                    {d}
                  </text>
                ))}
                {[0, 0.5, 1].map((a) => (
                  <text key={a} x={L - 8} y={yOf(a) + 4} className="k-axis-text" textAnchor="end">
                    {pct(a)}
                  </text>
                ))}
                <text x={L + CW / 2} y={T + CH + 34} className="k-axis-title" textAnchor="middle">
                  Days past due
                </text>
                <text x={12} y={T + CH / 2} className="k-axis-title" textAnchor="middle" transform={`rotate(-90 12 ${T + CH / 2})`}>
                  Answer rate
                </text>
              </svg>
              {at && cell && (
                <div className="k-live-tip" style={tipAt(at, 240, 90)}>
                  <div className="k-live-tip-head">
                    <b>{pts(cell.u)}</b>
                    <span>{cell.u > 0.0005 ? "A call helps" : cell.u < -0.0005 ? "A call hurts" : "No difference"}</span>
                  </div>
                  <div className="k-live-tip-row tabular">
                    {cell.d} days past due · {pct(cell.a)} answer rate
                  </div>
                </div>
              )}
            </div>

            <div className="k-profile">
              <span className="k-ab-h">Selected profile</span>
              <label className="k-field">
                <span className="k-field-h">Days past due · {d0}</span>
                <input type="range" min={0} max={nx - 1} value={sel.i} onChange={(e) => setSel((q) => ({ ...q, i: Number(e.target.value) }))} className="k-profile-range" aria-label="Days past due" />
              </label>
              <label className="k-field">
                <span className="k-field-h">Answer rate · {pct(a0)}</span>
                <input type="range" min={0} max={ny - 1} value={sel.j} onChange={(e) => setSel((q) => ({ ...q, j: Number(e.target.value) }))} className="k-profile-range" aria-label="Answer rate" />
              </label>
              <div className="k-profile-read" data-sign={u > 0.0005 ? "up" : u < -0.0005 ? "down" : "flat"}>
                <span className="v tabular">{pts(u)}</span>
                <span className="k">{u > 0.0005 ? "A call helps" : u < -0.0005 ? "A call hurts" : "No difference"}</span>
              </div>
              <p className="k-profile-text">
                For a customer {d0} days past due who answers {pct(a0)} of calls, a call {u >= 0 ? "adds" : "takes"} {Math.abs(u * 100).toFixed(1)} points {u >= 0 ? "to" : "from"} the chance of payment within 14
                days, compared with waiting.
              </p>
              <div>
                <span className="k-field-h">Tonight&apos;s cases near this profile · {n(closeN)}</span>
                {closeN > 0 ? (
                  <>
                    <span className="k-tierbar" aria-hidden>
                      {mix.map(([a, c]) => (
                        <i key={a} style={{ flex: c, background: ACTION_COLOR[a] ?? ACTION_COLOR.none }} />
                      ))}
                    </span>
                    <Flex gap="3" mt="2" wrap="wrap">
                      {mix.slice(0, 4).map(([a, c]) => (
                        <Text key={a} size="1" color="gray" className="tabular">
                          {actionName(a)} {pct(c / closeN)}
                        </Text>
                      ))}
                    </Flex>
                  </>
                ) : (
                  <Text as="p" size="1" color="gray" mt="1">
                    No group of 50 or more cases here.
                  </Text>
                )}
              </div>
            </div>
          </Grid>

          <Grid columns={{ initial: "1", md: "3" }} gap="3" mt="3">
            <Slice title={`Across days past due, at ${pct(a0)} answer rate`} xs={data.dpd} ys={data.uplift[sel.j]} sel={sel.i} big={big} fmtX={(v) => `${v} d`} onPick={(i) => setSel((q) => ({ ...q, i }))} />
            <Slice
              title={`Across answer rate, at ${d0} days past due`}
              xs={data.answer_rate}
              ys={data.uplift.map((row) => row[sel.i])}
              sel={sel.j}
              big={big}
              fmtX={(v) => pct(v)}
              onPick={(j) => setSel((q) => ({ ...q, j }))}
            />
            <div className="k-slice">
              <Flex justify="between" align="baseline">
                <Text size="1" weight="medium">
                  Tonight&apos;s cases by call uplift
                </Text>
                <Text size="1" color="gray" className="tabular">
                  {pct(helped / total)} helped
                </Text>
              </Flex>
              <svg viewBox="0 0 360 140" className="k-slice-svg" role="img" aria-label="Tonight's cases by predicted call uplift">
                {keys.map((k, idx) => {
                  const bw = 332 / keys.length;
                  const hgt = (bins.get(k)! / bMax) * 100;
                  return <rect key={k} x={28 + idx * bw} y={118 - hgt} width={bw - 2} height={hgt} rx={2} fill={diverge((k + 0.5) * binW, big)} />;
                })}
                {(() => {
                  const idx = keys.findIndex((k) => k === Math.floor(u / binW));
                  if (idx < 0) return null;
                  const bw = 332 / keys.length;
                  return <line x1={28 + (idx + 0.5) * bw} x2={28 + (idx + 0.5) * bw} y1={8} y2={120} className="k-slice-sel" />;
                })()}
                <text x={28} y={134} className="k-axis-text">
                  {pts(keys[0] * binW)}
                </text>
                <text x={360} y={134} className="k-axis-text" textAnchor="end">
                  {pts((keys[keys.length - 1] + 1) * binW)}
                </text>
              </svg>
            </div>
          </Grid>
        </>
      )}
      <Flex gap="4" mt="3" wrap="wrap" align="center">
        <span className="k-live-heatkey k-diverge">
          {pts(-big)} <i /> {pts(big)}
        </span>
        {actions.map((a) => (
          <Flex key={a} align="center" gap="2">
            <span className="k-uplift-keydot" style={{ background: ACTION_COLOR[a] ?? ACTION_COLOR.none }} />
            <Text size="1" color="gray">
              {actionName(a)}
            </Text>
          </Flex>
        ))}
      </Flex>
    </Box>
  );
}

// ------------------------------------------------------------------ overdue by postal district (#102)
type DLayer = "overdue" | "roll" | "hardship" | "red";
const DLAYERS: Record<DLayer, { label: string; value: (t: CollectionsMap["towers"][number]) => number | null; fmt: (v: number) => string; what: string }> = {
  overdue: { label: "Overdue balance", value: (t) => t.overdue, fmt: (v) => money(v), what: "Dot size and shade: tonight's overdue balance" },
  roll: { label: "Roll rate", value: (t) => t.roll_rate, fmt: (v) => pct(v), what: "Share of the bank's cases from the last 12 months that were 30+ days further behind by day 30" },
  hardship: { label: "Hardship share", value: (t) => t.hardship, fmt: (v) => pct(v), what: "Share of tonight's cases with a hardship signal" },
  red: { label: "Red tier share", value: (t) => t.red / Math.max(1, t.cases), fmt: (v) => pct(v), what: "Share of tonight's cards a hardship specialist reviews first" },
};
const REGIONS: [string, string[]][] = [
  ["Canada", []],
  ["Atlantic", ["NL", "NS", "PE", "NB"]],
  ["Quebec", ["QC"]],
  ["Ontario", ["ON"]],
  ["Prairies", ["MB", "SK", "AB"]],
  ["British Columbia", ["BC"]],
];
const TIER_COLOR = { green: "#3e9b5c", amber: "#e2a336", red: "#c8102e", none: "#a8a29e" } as const;
/** Low to high through green, amber and red: the roll-rate scale, the same as the 3D towers. */
const traffic = (t: number) => {
  const v = Math.max(0, Math.min(1, t)) * 2;
  return v <= 1
    ? `color-mix(in oklab, #e2a336 ${Math.round(v * 100)}%, #3e9b5c)`
    : `color-mix(in oklab, #c8102e ${Math.round((v - 1) * 100)}%, #e2a336)`;
};

/** Every postal district as a dot sized by its overdue balance and shaded by the chosen measure, on a map that zooms
 * (wheel, drag, or a region) and links to a ranked list. */
export function DistrictMap({ data, towers }: { data: CollectionsMap; towers: (mode: "roll" | "tier") => React.ReactNode }) {
  const map = useMap();
  const [view, setView] = useState<"map" | "towers">("map");
  const [layer, setLayer] = useState<DLayer>("roll");
  const [hover, setHover] = useState<string | null>(null);
  const [at, setAt] = useState<Tip | null>(null);
  const [z, setZ] = useState({ k: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; zx: number; zy: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const L = DLAYERS[layer];
  const ts = data.towers;
  const vals = ts.map(L.value).filter((v): v is number => v != null);
  const [lo, hi] = [Math.min(...vals), Math.max(...vals)];
  const maxOver = Math.max(1, ...ts.map((t) => t.overdue));
  const shade = (v: number | null) => (v == null ? "var(--k-closed)" : layer === "roll" ? traffic((v - lo) / (hi - lo || 1)) : ramp((v - lo) / (hi - lo || 1)));
  const totalOver = ts.reduce((sum, t) => sum + t.overdue, 0);
  const totalCases = ts.reduce((sum, t) => sum + t.cases, 0);
  const redCases = ts.reduce((sum, t) => sum + t.red, 0);
  const ranked = [...ts].filter((t) => L.value(t) != null && t.cases >= 50).sort((a, b) => L.value(b)! - L.value(a)!);
  const topRoll = [...ts].filter((t) => t.roll_rate != null && t.roll_base >= 50).sort((a, b) => b.roll_rate! - a.roll_rate!)[0];
  const pos = useMemo(() => (map ? new Map(ts.map((t) => [t.fsa, map.fit(...project(t.lon, t.lat))])) : null), [map, ts]);
  const h = hover ? ts.find((t) => t.fsa === hover) : undefined;

  const zoomTo = (codes: string[]) => {
    if (!map || !pos) return;
    if (!codes.length) return setZ({ k: 1, x: 0, y: 0 });
    const pts = ts.filter((t) => t.province && codes.includes(t.province)).map((t) => pos.get(t.fsa)!);
    if (!pts.length) return;
    const [x0, x1] = [Math.min(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0]))];
    const [y0, y1] = [Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[1]))];
    const k = Math.min(8, 0.8 * Math.min(W / Math.max(20, x1 - x0), map.H / Math.max(20, y1 - y0)));
    setZ({ k, x: W / 2 - ((x0 + x1) / 2) * k, y: map.H / 2 - ((y0 + y1) / 2) * k });
  };
  const toSvg = (e: { clientX: number; clientY: number }) => {
    const r = wrap.current!.querySelector("svg")!.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * (map?.H ?? 600)] as const;
  };
  // the wheel zooms the map, not the page: a native listener, since React's is passive
  const H = map?.H ?? 600;
  useEffect(() => {
    const el = wrap.current;
    if (!el || view !== "map") return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.querySelector("svg")?.getBoundingClientRect();
      if (!r) return;
      const [mx, my] = [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H];
      setZ((q) => {
        const k = Math.max(1, Math.min(12, q.k * (e.deltaY < 0 ? 1.25 : 0.8)));
        const f = k / q.k;
        return k === 1 ? { k: 1, x: 0, y: 0 } : { k, x: mx - (mx - q.x) * f, y: my - (my - q.y) * f };
      });
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [H, view]);
  const onDown = (e: React.PointerEvent) => {
    const [x, y] = toSvg(e);
    drag.current = { x, y, zx: z.x, zy: z.y };
  };
  const onMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const el = wrap.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setAt({ x: e.clientX - r.left, y: e.clientY - r.top, w: r.width, h: r.height });
    if (drag.current && z.k > 1) {
      const [x, y] = toSvg(e);
      setZ((q) => ({ ...q, x: drag.current!.zx + x - drag.current!.x, y: drag.current!.zy + y - drag.current!.y }));
    }
  };

  return (
    <Box>
      <Grid columns={{ initial: "1", md: "3" }} gap="3" mb="4">
        <Stat tint="butter" label="Overdue on the map" value={money(totalOver)} sub={`${n(totalCases)} cases in ${n(ts.length)} postal districts`} />
        <Stat tint="rose" label="Highest roll rate" value={topRoll ? `${topRoll.fsa} · ${pct(topRoll.roll_rate!)}` : "—"} sub={topRoll ? `${topRoll.city ?? topRoll.province ?? ""}, ${n(topRoll.roll_base)} past cases` : ""} />
        <Stat tint="lilac" label="Cases a specialist reviews first" value={pct(redCases / Math.max(1, totalCases))} sub={`${n(redCases)} Red cards tonight`} />
      </Grid>
      <Flex justify="between" align="center" mb="2" gap="2" wrap="wrap">
        <Flex gap="2" wrap="wrap">
          <Layers
            label="View"
            value={view}
            onChange={setView}
            options={[
              ["map", "Map"],
              ["towers", "3D towers"],
            ]}
          />
          {view === "map" && <Layers label="Measure" value={layer} onChange={setLayer} options={(Object.keys(DLAYERS) as DLayer[]).map((k) => [k, DLAYERS[k].label] as const)} />}
        </Flex>
        <Text size="1" color="gray">
          {L.what}
        </Text>
      </Flex>

      {view === "towers" ? (
        towers(layer === "red" ? "tier" : "roll")
      ) : (
        <Grid columns={{ initial: "1", md: "3fr 1.2fr" }} gap="4" align="start">
          <Box>
            <div
              ref={wrap}
              className="k-live-map k-district"
              data-zoomed={z.k > 1}
              onPointerDown={onDown}
              onPointerUp={() => (drag.current = null)}
              onPointerMove={onMove}
              onPointerLeave={() => ((drag.current = null), setHover(null), setAt(null))}
            >
              {map && pos ? (
                <svg viewBox={`0 0 ${W} ${map.H}`} className="k-geo k-district-svg" role="img" aria-label={`${L.label} by postal district`}>
                  <g transform={`translate(${z.x} ${z.y}) scale(${z.k})`}>
                    {map.provinces.map((p) => (
                      <path key={p.code} d={p.d} className="k-district-land" strokeWidth={0.8 / z.k} />
                    ))}
                    {[...ts]
                      .sort((a, b) => b.overdue - a.overdue)
                      .map((t) => {
                        const [x, y] = pos.get(t.fsa)!;
                        const r = (2.2 + 13 * Math.sqrt(t.overdue / maxOver)) / Math.sqrt(z.k);
                        return (
                          <circle
                            key={t.fsa}
                            cx={x}
                            cy={y}
                            r={r}
                            fill={layer === "overdue" ? ramp(Math.sqrt(t.overdue / maxOver)) : shade(L.value(t))}
                            strokeWidth={1 / z.k}
                            className="k-district-dot"
                            data-hover={hover === t.fsa}
                            data-dim={hover !== null && hover !== t.fsa}
                            onPointerEnter={() => setHover(t.fsa)}
                          />
                        );
                      })}
                  </g>
                </svg>
              ) : (
                <div className="k-geo-empty" />
              )}
              {h && at && (
                <div className="k-live-tip" style={tipAt(at)}>
                  <div className="k-live-tip-head">
                    <b>
                      {h.fsa}
                      {h.city ? ` · ${h.city}` : ""}
                    </b>
                    <span className="tabular">{h.province}</span>
                  </div>
                  <div className="k-live-tip-row tabular">
                    {n(h.cases)} cases · {money(h.overdue)} overdue
                  </div>
                  <div className="k-live-tip-row tabular">
                    Roll rate {h.roll_rate == null ? "—" : pct(h.roll_rate)} · hardship {pct(h.hardship)}
                  </div>
                  <span className="k-tierbar" aria-hidden>
                    {(["green", "amber", "red", "none"] as const).map((k) => (
                      <i key={k} style={{ flex: h[k], background: TIER_COLOR[k] }} />
                    ))}
                  </span>
                  <div className="k-live-tip-row tabular" style={{ fontSize: 11.5 }}>
                    Green {h.green} · Amber {h.amber} · Red {h.red} · No action {h.none}
                  </div>
                </div>
              )}
              <div className="k-zoom">
                <button className="k-round-btn" onClick={() => setZ((q) => ({ k: Math.min(12, q.k * 1.5), x: W / 2 - (W / 2 - q.x) * 1.5, y: (map?.H ?? 600) / 2 - ((map?.H ?? 600) / 2 - q.y) * 1.5 }))} aria-label="Zoom in">
                  +
                </button>
                <button className="k-round-btn" onClick={() => setZ((q) => (q.k / 1.5 <= 1 ? { k: 1, x: 0, y: 0 } : { k: q.k / 1.5, x: W / 2 - (W / 2 - q.x) / 1.5, y: (map?.H ?? 600) / 2 - ((map?.H ?? 600) / 2 - q.y) / 1.5 }))} aria-label="Zoom out">
                  −
                </button>
              </div>
            </div>
            <Flex gap="2" mt="3" wrap="wrap" align="center">
              {REGIONS.map(([name, codes]) => (
                <button key={name} className="k-tab" style={{ height: 30, padding: "0 12px" }} onClick={() => zoomTo(codes)}>
                  {name}
                </button>
              ))}
            </Flex>
            <Flex gap="4" mt="3" wrap="wrap" align="center">
              <span className="k-live-heatkey" data-traffic={layer === "roll"}>
                {L.fmt(layer === "overdue" ? 0 : lo)} <i /> {L.fmt(layer === "overdue" ? maxOver : hi)}
              </span>
              <Text size="1" color="gray">
                Dot size: overdue balance · {n(data.hidden_fsas)} districts with fewer than 50 cases left off
              </Text>
            </Flex>
          </Box>
          <Box className="k-live-side">
            <Flex justify="between" mb="2">
              <Text size="1" color="gray">
                Highest {L.label.toLowerCase()}
              </Text>
              <Text size="1" color="gray">
                Tier mix
              </Text>
            </Flex>
            <Flex direction="column" gap="1">
              {ranked.slice(0, 12).map((t) => (
                <SideRow key={t.fsa} code={t.fsa} value={L.fmt(L.value(t)!)} hover={hover} setHover={setHover}>
                  <span className="k-tierbar k-tierbar-sm" aria-hidden>
                    {(["green", "amber", "red", "none"] as const).map((k) => (
                      <i key={k} style={{ flex: t[k], background: TIER_COLOR[k] }} />
                    ))}
                  </span>
                </SideRow>
              ))}
            </Flex>
            <Flex gap="3" mt="2" wrap="wrap">
              {(["green", "amber", "red", "none"] as const).map((k) => (
                <Key key={k} swatch={TIER_COLOR[k]} label={k === "none" ? "No action" : k[0].toUpperCase() + k.slice(1)} />
              ))}
            </Flex>
            <Text as="p" size="1" color="gray" mt="3">
              Postal geography is shown for monitoring only; it is never a model input.
            </Text>
          </Box>
        </Grid>
      )}
    </Box>
  );
}

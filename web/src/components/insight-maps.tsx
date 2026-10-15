"use client";

// The two flat maps on the Insights page: calling hours by province now (#103) and financial stress by
// province over the last 12 month-ends (#112). Plain SVG on the projected provinces (lib/geo).
import { PauseIcon, PlayIcon, ResetIcon } from "@radix-ui/react-icons";
import { Box, Flex, Grid, Text } from "@radix-ui/themes";
import { useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import type { CallingHours, StressMap } from "@/lib/api";
import { useServerClock } from "@/lib/clock";
import { anchor, bounds, loadProvinces, localTime, svgPath, type Province } from "@/lib/geo";

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
      provinces: shapes.map((p) => ({ ...p, d: svgPath(p, fit), at: fit(...anchor(p)) })),
    };
  }, [shapes]);
}

function Shell({ H, label, children }: { H: number; label: string; children: React.ReactNode }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="k-geo" role="img" aria-label={label}>
      <defs>
        <pattern id="k-geo-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="6" height="6" fill="var(--k-card)" />
          <line x1="0" y1="0" x2="0" y2="6" stroke="var(--k-hatch)" strokeWidth="2" />
        </pattern>
      </defs>
      {children}
    </svg>
  );
}

// ------------------------------------------------------------------ calling hours (#103)
const PER_DOT = 40;
const EAST_TO_WEST = ["NL", "NS", "PE", "NB", "QC", "NU", "ON", "MB", "SK", "AB", "NT", "BC", "YT"];

/** Minutes since midnight Eastern, and the instant of that midnight. */
function etDay(t: number) {
  const m = localTime(t, ET).minutes;
  return { minutes: m, midnight: Math.floor(t / 60000) * 60000 - m * 60000 };
}

export function CallingHoursMap({ data }: { data: CallingHours }) {
  const map = useMap();
  const calm = useReducedMotion() ?? false;
  const clock = useServerClock().now; // the app's clock: business hours on the demo server
  const [boot] = useState(() => Date.now());
  const [picked, setPicked] = useState<number | null>(null); // null: follow the clock
  const [playing, setPlaying] = useState(false);
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
    for (const b of data.bank) {
      at.set(`${b.province}|${b.day}|${b.hour}`, b.contacts);
      total.set(b.province, (total.get(b.province) ?? 0) + b.contacts);
    }
    return { at, total };
  }, [data.bank]);

  const rows = data.provinces.map((p) => {
    const lt = localTime(t, p.time_zone);
    const [s, e] = [p.start, p.end].map((x) => Number(x.slice(0, 2)) * 60 + Number(x.slice(3, 5)));
    const inside = lt.minutes >= s && lt.minutes < e;
    const share = !inside ? 0 : lt.day === "Sun" ? p.sunday_share : 1; // permission_gate: no Sunday unless allowed
    const status = share >= 0.999 ? "open" : share > 0 ? "partial" : "closed";
    return { ...p, lt, share, status, now: bank.at.get(`${p.province}|${lt.day}|${Math.floor(lt.minutes / 60)}`) ?? 0 };
  });
  const by = new Map(rows.map((r) => [r.province, r]));
  const open = rows.filter((r) => r.status !== "closed").length;
  const nowContacts = rows.reduce((s, r) => s + r.now, 0);
  const { minutes, midnight } = etDay(t);
  const etLabel = localTime(t, ET).label;
  const today = localTime(t, ET).day;

  const scrub = (next: number) => setPicked(next);

  return (
    <Box>
      <Grid columns={{ initial: "1", md: "3" }} gap="3" mb="4">
        <Stat tint="mint" label="Provinces open now" value={`${open} of ${rows.length}`} sub={`${etLabel} Eastern${live ? " · live" : ""}`} />
        <Stat
          tint="rose"
          label="Bank: contacts outside permitted hours"
          value={n(data.bank_contacts)}
          sub={`${n(data.bank_cases)} cases, ${pct(data.bank_cases / Math.max(1, data.cases), 1)} of all`}
        />
        <Stat tint="ice" label="Kept: cards outside permitted hours" value={n(data.kept_outside)} sub={`of ${n(data.kept_cards)} contact cards tonight`} />
      </Grid>

      <Grid columns={{ initial: "1", md: "3fr 1fr" }} gap="4" align="start">
        <Box>
          {map ? (
            <Shell H={map.H} label={`Calling hours by province at ${etLabel} Eastern: ${open} of ${rows.length} open`}>
              {map.provinces.map((p) => {
                const r = by.get(p.code);
                const fill = !r
                  ? "url(#k-geo-hatch)"
                  : r.status === "open"
                    ? "var(--k-mint-2)"
                    : r.status === "partial"
                      ? `color-mix(in oklab, var(--k-mint-2) ${Math.round(r.share * 100)}%, var(--k-card))`
                      : "var(--k-closed)";
                return (
                  <path key={p.code} d={p.d} fill={fill} className="k-geo-shape" data-calm={calm}>
                    <title>
                      {r ? `${p.name}: ${r.lt.label} local, ${r.status === "open" ? "open" : r.status === "partial" ? `Sunday, open for ${pct(r.share)} of customers` : "closed"}` : `${p.name}: fewer than 50 customers`}
                    </title>
                  </path>
                );
              })}
              {map.provinces.map((p) => {
                const total = bank.total.get(p.code) ?? 0;
                const r = by.get(p.code);
                if (!total || !r) return null;
                const dots = Math.max(1, Math.round(total / PER_DOT));
                return (
                  <g key={p.code} className="k-geo-dots" data-hot={r.now > 0}>
                    {Array.from({ length: dots }, (_, i) => {
                      const rr = 4.2 * Math.sqrt(i + 0.5);
                      const a = i * 2.39996;
                      return <circle key={i} cx={p.at[0] + rr * Math.cos(a)} cy={p.at[1] + rr * Math.sin(a)} r={1.9} />;
                    })}
                    <title>{`${p.name}: the bank made ${n(total)} contacts outside permitted hours${r.now ? `, ${n(r.now)} of them at ${r.lt.day} ${String(Math.floor(r.lt.minutes / 60)).padStart(2, "0")}:00 local` : ""}`}</title>
                  </g>
                );
              })}
            </Shell>
          ) : (
            <div className="k-geo-empty" />
          )}

          <Flex align="center" gap="2" mt="3" wrap="wrap">
            <button className="k-round-btn" style={{ width: 34, height: 34 }} onClick={() => (setPicked(t), setPlaying((x) => !x))} aria-label={playing ? "Pause" : "Play the day"} title={playing ? "Pause" : "Play the day"}>
              {playing ? <PauseIcon /> : <PlayIcon />}
            </button>
            <button className="k-round-btn" style={{ width: 34, height: 34 }} onClick={() => (setPlaying(false), setPicked(null))} aria-label="Back to now" title="Back to now">
              <ResetIcon />
            </button>
            <div className="k-tabs">
              {DAYS.map((d, i) => (
                <button key={d} className="k-tab" data-active={d === today} style={{ height: 30, padding: "0 10px" }} onClick={() => scrub(t + (i - DAYS.indexOf(today)) * 86_400_000)}>
                  {d}
                </button>
              ))}
            </div>
          </Flex>
          <input
            type="range"
            className="k-scrub"
            min={0}
            max={1435}
            step={5}
            value={minutes}
            onChange={(e) => scrub(midnight + Number(e.target.value) * 60000)}
            aria-label="Time of day, Eastern"
            aria-valuetext={`${etLabel} Eastern`}
          />
          <Flex justify="between">
            {["00:00", "06:00", "12:00", "18:00", "24:00"].map((h) => (
              <Text key={h} size="1" color="gray" className="tabular">
                {h}
              </Text>
            ))}
          </Flex>
          <Flex gap="4" mt="2" wrap="wrap" align="center">
            <Key swatch="var(--k-mint-2)" label="Open: 07:00 to 21:00 local" />
            <Key swatch="color-mix(in oklab, var(--k-mint-2) 50%, var(--k-card))" label="Sunday: open only for customers who allow it" />
            <Key swatch="var(--k-closed)" label="Closed" />
            <Key dot label={`Bank contact outside hours (one dot = ${PER_DOT})`} />
          </Flex>
        </Box>

        <Box>
          <Text as="div" size="1" color="gray" mb="2">
            Local time and status
          </Text>
          <Flex direction="column" gap="1">
            {[...rows]
              .sort((a, b) => EAST_TO_WEST.indexOf(a.province) - EAST_TO_WEST.indexOf(b.province))
              .map((r) => (
                <Flex key={r.province} justify="between" align="center" className="k-geo-row" data-status={r.status}>
                  <Text size="2" weight="medium">
                    {r.province}
                  </Text>
                  <Text size="1" className="tabular" color="gray">
                    {r.lt.label}
                  </Text>
                  <span className="k-geo-pill">{r.status === "open" ? "Open" : r.status === "partial" ? `${pct(r.share)}` : "Closed"}</span>
                </Flex>
              ))}
          </Flex>
          <Text as="p" size="1" color="gray" mt="3">
            At this local hour and weekday the bank&apos;s history shows <b>{n(nowContacts)}</b> contacts outside permitted hours. Kept proposes a contact only inside the customer&apos;s window, and checks it again at release.
          </Text>
        </Box>
      </Grid>
    </Box>
  );
}

function Stat({ tint, label, value, sub }: { tint: string; label: string; value: string; sub: string }) {
  return (
    <div className={`k-card t-${tint}`} style={{ padding: 16 }}>
      <Text as="div" size="1" weight="medium">
        {label}
      </Text>
      <div className="k-big tabular" style={{ fontSize: 28, marginTop: 6 }}>
        {value}
      </div>
      <Text as="div" size="1" color="gray">
        {sub}
      </Text>
    </div>
  );
}

function Key({ swatch, label, dot = false }: { swatch?: string; label: string; dot?: boolean }) {
  return (
    <Flex align="center" gap="2">
      {dot ? <span className="k-geo-keydot" /> : <span className="k-geo-swatch" style={{ background: swatch }} />}
      <Text size="1" color="gray">
        {label}
      </Text>
    </Flex>
  );
}

// ------------------------------------------------------------------ stress map (#112)
type Metric = "falling_cash_flow" | "payroll_delay" | "hardship";
const METRICS: Record<Metric, { label: string; what: string; base: (c: StressMap["cells"][number]) => number; baseLabel: string }> = {
  falling_cash_flow: {
    label: "Falling cash flow",
    what: "Net cash flow lower than at the month-end before",
    base: (c) => c.cash_flow_base,
    baseLabel: "customers with a deposit account",
  },
  payroll_delay: {
    label: "Payroll delay",
    what: "Employer pay arrived more than 5 days after it was due",
    base: (c) => c.payroll_base,
    baseLabel: "customers paid by an employer that month",
  },
  hardship: {
    label: "Hardship flag",
    what: "A hardship-flagged collections case open at the month-end",
    base: (c) => c.customers,
    baseLabel: "customers",
  },
};
const monthLabel = (d: string) => new Date(`${d}T12:00:00Z`).toLocaleDateString("en-CA", { month: "short", year: "numeric", timeZone: "UTC" });

export function StressMapView({ data }: { data: StressMap }) {
  const map = useMap();
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
  const vals = data.cells.map((c) => c[metric]).filter((v): v is number => v != null);
  const [lo, hi] = [Math.min(...vals, 0), Math.max(...vals, 0.0001)];
  const cells = new Map(data.cells.filter((c) => c.month === month).map((c) => [c.province, c]));
  const m = METRICS[metric];
  const fillOf = (v: number | null | undefined) =>
    v == null ? "url(#k-geo-hatch)" : `color-mix(in oklab, var(--k-red) ${Math.round(6 + ((v - lo) / (hi - lo || 1)) * 84)}%, var(--k-chip))`;
  const ranked = [...cells.values()].sort((a, b) => (b[metric] ?? -1) - (a[metric] ?? -1));
  const focus = hover ? cells.get(hover) : undefined;

  return (
    <Box>
      <Flex gap="2" wrap="wrap" align="center" mb="3">
        <div className="k-tabs">
          {(Object.keys(METRICS) as Metric[]).map((k) => (
            <button key={k} className="k-tab" data-active={metric === k} style={{ height: 32 }} onClick={() => setMetric(k)}>
              {METRICS[k].label}
            </button>
          ))}
        </div>
        <Text size="1" color="gray">
          {m.what}. Share of {m.baseLabel}.
        </Text>
      </Flex>

      <Grid columns={{ initial: "1", md: "3fr 1fr" }} gap="4" align="start">
        <Box style={{ position: "relative" }}>
          {map ? (
            <Shell H={map.H} label={`${m.label} by province, ${monthLabel(month)}`}>
              {map.provinces.map((p) => {
                const c = cells.get(p.code);
                return (
                  <path
                    key={p.code}
                    d={p.d}
                    fill={fillOf(c?.[metric])}
                    className="k-geo-shape"
                    data-calm={calm}
                    data-hover={hover === p.code}
                    onMouseEnter={() => setHover(p.code)}
                    onMouseLeave={() => setHover(null)}
                  >
                    <title>{c?.[metric] != null ? `${p.name}: ${pct(c[metric]!, 1)} of ${n(m.base(c))}` : `${p.name}: fewer than 50 customers, or no earlier month`}</title>
                  </path>
                );
              })}
            </Shell>
          ) : (
            <div className="k-geo-empty" />
          )}
          <div className="k-geo-tip" data-show={!!focus}>
            {focus && (
              <>
                <b>{map?.provinces.find((p) => p.code === focus.province)?.name}</b> · {monthLabel(month)}
                <br />
                {focus[metric] != null ? `${pct(focus[metric]!, 1)} of ${n(m.base(focus))} ${m.baseLabel}` : "Too few customers to show"}
              </>
            )}
          </div>

          <Flex align="center" gap="3" mt="3">
            <button className="k-round-btn" style={{ width: 34, height: 34, flex: "none" }} onClick={() => setPlaying((x) => !x)} aria-label={playing ? "Pause" : "Play the months"} title={playing ? "Pause" : "Play the months"}>
              {playing ? <PauseIcon /> : <PlayIcon />}
            </button>
            <input
              type="range"
              className="k-scrub"
              min={0}
              max={data.months.length - 1}
              value={i}
              onChange={(e) => (setPlaying(false), setI(Number(e.target.value)))}
              aria-label="Month-end"
              aria-valuetext={monthLabel(month)}
            />
            <Text size="2" weight="medium" className="tabular" style={{ whiteSpace: "nowrap", minWidth: 76 }}>
              {monthLabel(month)}
            </Text>
          </Flex>
          <Flex align="center" gap="2" mt="2" wrap="wrap">
            <Text size="1" color="gray" className="tabular">
              {pct(lo)}
            </Text>
            <span className="k-geo-scale" />
            <Text size="1" color="gray" className="tabular">
              {pct(hi)}
            </Text>
            <span className="k-geo-swatch k-geo-hatched" style={{ marginLeft: 12 }} />
            <Text size="1" color="gray">
              Fewer than 50, or no earlier month to compare
            </Text>
          </Flex>
        </Box>

        <Box>
          <Text as="div" size="1" color="gray" mb="2">
            {m.label}, {monthLabel(month)}
          </Text>
          <Flex direction="column" gap="1">
            {ranked.map((c) => (
              <Box key={c.province} onMouseEnter={() => setHover(c.province)} onMouseLeave={() => setHover(null)} className="k-geo-row" data-hover={hover === c.province}>
                <Flex justify="between">
                  <Text size="2" weight="medium">
                    {c.province}
                  </Text>
                  <Text size="1" className="tabular" color="gray">
                    {c[metric] == null ? "—" : pct(c[metric]!, 1)}
                  </Text>
                </Flex>
                <div className="k-act-track" style={{ height: 4, marginTop: 2 }}>
                  <span className="k-act-bar" style={{ width: `${((c[metric] ?? 0) / (hi || 1)) * 100}%`, background: "var(--k-red)" }} />
                </div>
              </Box>
            ))}
          </Flex>
        </Box>
      </Grid>
    </Box>
  );
}

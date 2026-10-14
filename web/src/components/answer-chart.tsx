"use client";

// Charts for Ask answers (#100). The API (kept.app.charts) decides WHAT to draw: one of a fixed set of options
// the rows support, picked by the LLM or the rules. This file only draws it: a number tile, horizontal bars,
// grouped bars or lines, in plain SVG with the app's theme tokens. Every value drawn comes from the rows.
import { Box, Flex, Grid, Text } from "@radix-ui/themes";
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { ChartOption } from "@/lib/api";

type Unit = ChartOption["unit"];
type Series = { name: string; color: string; values: (number | null)[] };
type Tip = { x: number; y: number; w?: number; title: string; rows: { name: string; color: string; value: string }[] } | null;

const COLORS = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)"];
const INK = "var(--gray-12)";
const MUTED = "var(--gray-11)";
const GRID = "var(--gray-a4)";
const AXIS = "var(--gray-a7)";
const SURFACE = "var(--color-panel-solid)";

/** A cell as a number: the API sends Decimals as strings ("0.42"). */
export function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v.trim())) return Number(v);
  return null;
}

export function fmt(v: number | null, unit: Unit, compact = false): string {
  if (v == null) return "—";
  if (unit === "fraction") return `${(v * 100).toFixed(1)}%`;
  if (unit === "percent") return `${v.toFixed(1)}%`;
  const big = compact || Math.abs(v) >= 100_000;
  if (unit === "money") {
    const a = Math.abs(v);
    const digits = big ? 1 : a === 0 || a >= 100 ? 0 : a >= 0.1 ? 2 : 3; // $1.75, $0.01, $0.001: never round a unit cost away
    return new Intl.NumberFormat("en-CA", { style: "currency", currency: "CAD", currencyDisplay: "narrowSymbol", notation: big ? "compact" : "standard", minimumFractionDigits: big || a >= 100 ? 0 : Math.min(2, digits), maximumFractionDigits: digits }).format(v);
  }
  return new Intl.NumberFormat("en-CA", { notation: big ? "compact" : "standard", maximumFractionDigits: unit === "count" ? 0 : 2 }).format(v);
}

const label = (s: string) => (s.length > 22 ? `${s.slice(0, 21)}…` : s);
const humanize = (s: string) => (s.charAt(0).toUpperCase() + s.slice(1)).replaceAll("_", " ");

/** Clean axis ticks from lo to hi (always including 0 for bars). */
function ticks(lo: number, hi: number, n = 4): number[] {
  if (lo === hi) hi = lo + (lo === 0 ? 1 : Math.abs(lo) * 0.1);
  const raw = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let t = Math.floor(lo / step) * step; t <= hi + step * 1e-9; t += step) out.push(Number(t.toFixed(10)));
  if (out[out.length - 1] < hi) out.push(out[out.length - 1] + step);
  return out;
}

/** The element's width in CSS px, so the SVG draws at 1:1 and 11px text stays 11px at any card width. */
function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [w, setW] = useState(640);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(320, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** Bar with a 4px rounded data end and a square end at the baseline (horizontal, growing right from x0). */
function hbar(x0: number, x1: number, y: number, h: number): string {
  const r = Math.min(4, Math.abs(x1 - x0), h / 2);
  if (x1 >= x0) return `M${x0},${y}H${x1 - r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 - r},${y + h}H${x0}Z`;
  return `M${x0},${y}H${x1 + r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 + r},${y + h}H${x0}Z`;
}

export function AnswerChart({ option, columns, rows }: { option: ChartOption; columns: string[]; rows: unknown[][] }) {
  const [tip, setTip] = useState<Tip>(null);
  const [hover, setHover] = useState(-1); // line: the x index under the crosshair
  const [box, W] = useWidth();
  const col = (name: string | null | undefined) => (name ? columns.indexOf(name) : -1);
  const unit = option.unit ?? "number";
  const ys = option.y ?? [];

  const data = useMemo(() => {
    const xi = col(option.x);
    const si = col(option.series);
    if (option.kind === "tile") return null;
    // Categories (bars) or x positions (lines), in display order.
    let xs = Array.from(new Set(rows.map((r) => String(r[xi] ?? "—"))));
    let series: Series[];
    if (si >= 0) {
      const yi = col(ys[0]);
      const names = Array.from(new Set(rows.map((r) => String(r[si] ?? "—")))).slice(0, 4);
      series = names.map((name, k) => ({
        name,
        color: COLORS[k],
        values: xs.map((x) => num(rows.find((r) => String(r[xi]) === x && String(r[si]) === name)?.[yi])),
      }));
    } else {
      series = ys.slice(0, 4).map((y, k) => {
        const yi = col(y);
        return { name: y, color: COLORS[k], values: xs.map((x) => num(rows.find((r) => String(r[xi] ?? "—") === x)?.[yi])) };
      });
    }
    if (option.kind === "line") {
      const order = xs.map((x, i) => [x, i] as const).sort((a, b) => a[0].localeCompare(b[0]));
      xs = order.map(([x]) => x);
      series = series.map((s) => ({ ...s, values: order.map(([, i]) => s.values[i]) }));
    } else {
      const order = xs.map((x, i) => [x, i] as const).sort((a, b) => (series[0].values[b[1]] ?? -Infinity) - (series[0].values[a[1]] ?? -Infinity));
      xs = order.map(([x]) => x);
      series = series.map((s) => ({ ...s, values: order.map(([, i]) => s.values[i]) }));
    }
    return { xs, series };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [option, columns, rows]);

  if (option.kind === "table") return null;

  if (option.kind === "tile") {
    return (
      <Grid columns={{ initial: "1", sm: String(Math.min(ys.length, 4)) }} gap="4" role="group" aria-label={option.title}>
        {ys.map((y) => {
          const v = num(rows[0]?.[col(y)]);
          return (
            <Box key={y}>
              <Text as="div" size="2" color="gray">{humanize(y)}</Text>
              <Text as="div" weight="bold" style={{ fontSize: 48, lineHeight: 1.1, fontFamily: "var(--default-font-family)" }}>{fmt(v, unit)}</Text>
            </Box>
          );
        })}
      </Grid>
    );
  }

  if (!data || data.xs.length === 0) return null;
  const legend = data.series.length >= 2 && (
    <Flex gap="4" wrap="wrap" mb="2" aria-hidden>
      {data.series.map((s) => (
        <Flex key={s.name} align="center" gap="2">
          {option.kind === "line" ? <svg width="16" height="8"><line x1="0" x2="16" y1="4" y2="4" stroke={s.color} strokeWidth="2" strokeLinecap="round" /></svg> : <svg width="10" height="10"><rect width="10" height="10" rx="2" fill={s.color} /></svg>}
          <Text size="1" color="gray">{humanize(s.name)}</Text>
        </Flex>
      ))}
    </Flex>
  );

  const move = (e: ReactPointerEvent<Element>, title: string, rowsOut: NonNullable<Tip>["rows"]) => {
    const box = (e.currentTarget as Element).closest("[data-chart]")!.getBoundingClientRect();
    setTip({ x: e.clientX - box.left, y: e.clientY - box.top, w: box.width, title, rows: rowsOut });
  };

  const tooltip = tip && (
    <Box
      style={{ position: "absolute", ...(tip.w && tip.x > tip.w * 0.6 ? { right: tip.w - tip.x + 12 } : { left: tip.x + 12 }), top: tip.y + 12, pointerEvents: "none", background: "var(--color-panel-solid)", border: "1px solid var(--gray-a5)", borderRadius: 6, padding: "6px 10px", boxShadow: "var(--shadow-3)", zIndex: 2, whiteSpace: "nowrap" }}
    >
      <Text as="div" size="1" color="gray">{tip.title}</Text>
      {tip.rows.map((r) => (
        <Flex key={r.name} align="center" gap="2">
          <svg width="12" height="4" aria-hidden><line x1="0" x2="12" y1="2" y2="2" stroke={r.color} strokeWidth="2" /></svg>
          <Text size="2" weight="bold" className="tabular">{r.value}</Text>
          {tip.rows.length > 1 && <Text size="1" color="gray">{humanize(r.name)}</Text>}
        </Flex>
      ))}
    </Box>
  );

  const values = data.series.flatMap((s) => s.values).filter((v): v is number => v != null);
  const desc = `${option.kind === "line" ? "Line" : "Bar"} chart: ${option.title}`;

  if (option.kind === "bar" || option.kind === "grouped_bar") {
    const k = data.series.length;
    const thick = k === 1 ? 20 : Math.max(8, Math.min(16, Math.floor(28 / k)));
    const band = k * thick + (k - 1) * 2 + 14;
    const left = 150;
    const right = 70;
    const top = 22;
    const H = top + data.xs.length * band + 6;
    const t = ticks(Math.min(0, ...values), Math.max(0, ...values));
    const sx = (v: number) => left + ((v - t[0]) / (t[t.length - 1] - t[0])) * (W - left - right);
    return (
      <Box>
        {legend}
        <Box data-chart ref={box} style={{ position: "relative" }} onPointerLeave={() => setTip(null)}>
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={desc}>
            <title>{desc}</title>
            {t.map((v) => (
              <g key={v}>
                <line x1={sx(v)} x2={sx(v)} y1={top - 4} y2={H - 6} stroke={v === 0 ? AXIS : GRID} strokeWidth="1" />
                <text x={sx(v)} y={top - 9} textAnchor="middle" fontSize="11" fill={MUTED} className="tabular">{fmt(v, unit, true)}</text>
              </g>
            ))}
            {data.xs.map((x, i) => {
              const y0 = top + i * band + 7;
              return (
                <g key={x}>
                  <text x={left - 10} y={y0 + (k * thick + (k - 1) * 2) / 2} dominantBaseline="middle" textAnchor="end" fontSize="12" fill={INK}>
                    <title>{x}</title>
                    {label(x)}
                  </text>
                  {data.series.map((s, j) => {
                    const v = s.values[i];
                    if (v == null) return null;
                    const y = y0 + j * (thick + 2);
                    const rowsOut = data.series.map((ss) => ({ name: ss.name, color: ss.color, value: fmt(ss.values[i], unit) }));
                    return (
                      <g key={s.name} tabIndex={0} role="img" aria-label={`${x}${k > 1 ? `, ${humanize(s.name)}` : ""}: ${fmt(v, unit)}`}
                        onPointerMove={(e) => move(e, x, rowsOut)} onFocus={() => setTip({ x: sx(v), y, title: x, rows: rowsOut })} onBlur={() => setTip(null)} style={{ outline: "none" }}>
                        <rect x={left} y={y - 1} width={W - left - right + 60} height={thick + 2} fill="transparent" />
                        <path d={hbar(sx(0), sx(v), y, thick)} fill={s.color} opacity={tip && tip.title !== x ? 0.55 : 1} />
                        {(k === 1 || data.xs.length <= 6) && (
                          <text x={sx(v) + (v >= 0 ? 6 : -6)} y={y + thick / 2} dominantBaseline="middle" textAnchor={v >= 0 ? "start" : "end"} fontSize="11" fill={MUTED} className="tabular">{fmt(v, unit)}</text>
                        )}
                      </g>
                    );
                  })}
                </g>
              );
            })}
          </svg>
          {tooltip}
        </Box>
      </Box>
    );
  }

  // Line: evenly spaced x (ordered time), one axis, end value labelled, crosshair snaps to the nearest x.
  const H = 280;
  const left = 56;
  const right = 64;
  const top = 16;
  const bottom = 30;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.1;
  const t = ticks(unit === "count" || unit === "money" ? Math.min(0, lo) : lo - pad, hi + pad);
  const n = data.xs.length;
  const sx = (i: number) => left + (n === 1 ? 0.5 : i / (n - 1)) * (W - left - right);
  const sy = (v: number) => top + (1 - (v - t[0]) / (t[t.length - 1] - t[0])) * (H - top - bottom);
  const every = Math.ceil(n / 6);
  return (
    <Box>
      {legend}
      <Box data-chart ref={box} style={{ position: "relative" }} onPointerLeave={() => { setTip(null); setHover(-1); }}>
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={desc}>
          <title>{desc}</title>
          {t.map((v) => (
            <g key={v}>
              <line x1={left} x2={W - right} y1={sy(v)} y2={sy(v)} stroke={GRID} strokeWidth="1" />
              <text x={left - 8} y={sy(v)} dominantBaseline="middle" textAnchor="end" fontSize="11" fill={MUTED} className="tabular">{fmt(v, unit, true)}</text>
            </g>
          ))}
          <line x1={left} x2={W - right} y1={H - bottom} y2={H - bottom} stroke={AXIS} strokeWidth="1" />
          {data.xs.map((x, i) =>
            i % every === 0 || i === n - 1 ? (
              <text key={x} x={sx(i)} y={H - bottom + 18} textAnchor="middle" fontSize="11" fill={MUTED}>{label(x)}</text>
            ) : null,
          )}
          {hover >= 0 && hover < n && <line x1={sx(hover)} x2={sx(hover)} y1={top} y2={H - bottom} stroke={AXIS} strokeWidth="1" />}
          {data.series.map((s) => {
            const pts = s.values.map((v, i) => (v == null ? null : ([sx(i), sy(v)] as const)));
            const d = pts.reduce((acc, p, i) => (p ? `${acc}${acc && pts[i - 1] ? "L" : "M"}${p[0]},${p[1]}` : acc), "");
            const lastI = s.values.findLastIndex((v) => v != null);
            return (
              <g key={s.name}>
                <path d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
                {n <= 24 && pts.map((p, i) => p && <circle key={i} cx={p[0]} cy={p[1]} r={i === hover ? 6 : 4} fill={s.color} stroke={SURFACE} strokeWidth="2" />)}
                {lastI >= 0 && data.series.length <= 4 && (
                  <text x={sx(lastI) + 8} y={sy(s.values[lastI]!)} dominantBaseline="middle" fontSize="11" fill={MUTED} className="tabular">{fmt(s.values[lastI], unit)}</text>
                )}
              </g>
            );
          })}
          <rect
            x={left} y={top} width={W - left - right} height={H - top - bottom} fill="transparent"
            onPointerMove={(e) => {
              const box = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
              const vx = ((e.clientX - box.left) / box.width) * W;
              const i = Math.max(0, Math.min(n - 1, Math.round((vx - left) / ((W - left - right) / Math.max(1, n - 1)))));
              setHover(i);
              move(e, data.xs[i], data.series.map((s) => ({ name: s.name, color: s.color, value: fmt(s.values[i], unit) })));
            }}
          />
        </svg>
        {tooltip}
      </Box>
    </Box>
  );
}

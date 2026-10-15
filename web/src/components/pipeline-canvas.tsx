"use client";

import {
  ArchiveIcon,
  ChatBubbleIcon,
  CheckCircledIcon,
  ComponentInstanceIcon,
  FileTextIcon,
  LayersIcon,
  LightningBoltIcon,
  MixIcon,
  PersonIcon,
  ReaderIcon,
} from "@radix-ui/react-icons";
import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

type Tint = "ice" | "lilac" | "mint" | "butter" | "rose";
export type NodeId = "sources" | "identity" | "notes" | "features" | "models" | "decide" | "release" | "audit" | "ask";

/** The orchestration pipeline: where each part runs and what it does (positions on a 1000 × 214 canvas). */
const NODES: { id: NodeId; x: number; y: number; name: string; sub: string; detail: string; tint: Tint; icon: React.ReactNode }[] = [
  { id: "sources", x: 75, y: 150, name: "Source systems", sub: "5 systems", detail: "Cards, loans, deposits, CRM and collections, loaded nightly into DuckDB.", tint: "ice", icon: <ArchiveIcon /> },
  { id: "identity", x: 215, y: 150, name: "Identity", sub: "Splink · steward", detail: "Five customer keys resolved to one golden ID; uncertain pairs go to a data steward.", tint: "ice", icon: <PersonIcon /> },
  { id: "notes", x: 355, y: 44, name: "Notes and calls", sub: "Qwen3.8 · Whisper", detail: "Redacted, then read by the local model; every value quotes its source text.", tint: "lilac", icon: <FileTextIcon /> },
  { id: "features", x: 355, y: 150, name: "Features", sub: "dbt · Feast", detail: "Point-in-time features: payroll timing, cash flow, contact history, hardship.", tint: "ice", icon: <LayersIcon /> },
  { id: "models", x: 495, y: 150, name: "Models", sub: "Uplift · promise", detail: "LightGBM uplift per action against waiting, and a calibrated promise model.", tint: "lilac", icon: <MixIcon /> },
  { id: "ask", x: 635, y: 44, name: "Ask", sub: "LangGraph · Qwen3.8", detail: "Questions answered from certified metrics, reviewed templates or checked SQL, with sources.", tint: "lilac", icon: <ChatBubbleIcon /> },
  { id: "decide", x: 635, y: 150, name: "Decision", sub: "Rules · tiers", detail: "Hard stops before scoring; promises due on payday and sized to spare cash; Red, Amber or Green.", tint: "butter", icon: <LightningBoltIcon /> },
  { id: "release", x: 775, y: 150, name: "Release", sub: "Two-person rule", detail: "Red needs a hardship specialist and a second approver; every rule is rechecked at release.", tint: "rose", icon: <CheckCircledIcon /> },
  { id: "audit", x: 915, y: 150, name: "Audit", sub: "Hash chain", detail: "Every recommendation, model call and decision, append-only and hash-chained.", tint: "mint", icon: <ReaderIcon /> },
];
const EDGES: [NodeId, NodeId][] = [
  ["sources", "identity"],
  ["identity", "features"],
  ["notes", "features"],
  ["features", "models"],
  ["models", "decide"],
  ["decide", "release"],
  ["release", "audit"],
  ["features", "ask"],
];
const W = 1000;
const H = 214;
const TW = 118; // tile width and height on the canvas
const TH = 70;
const at = Object.fromEntries(NODES.map((n) => [n.id, n])) as Record<NodeId, (typeof NODES)[number]>;

/** A soft S-curve from one tile's right edge to the next tile's left edge (or straight up into a tile above). */
function edgePath(a: NodeId, b: NodeId): string {
  const p = at[a];
  const q = at[b];
  if (Math.abs(p.x - q.x) < 4) return `M${p.x},${p.y - TH / 2} L${q.x},${q.y + TH / 2}`;
  if (q.y < p.y - 40) {
    const x1 = p.x + TW / 2;
    return `M${x1},${p.y} C${x1 + 60},${p.y} ${q.x},${p.y - 10} ${q.x},${q.y + TH / 2}`;
  }
  const x1 = p.x + TW / 2;
  const x2 = q.x - TW / 2;
  const mx = (x1 + x2) / 2;
  return `M${x1},${p.y} C${mx},${p.y} ${mx},${q.y} ${x2},${q.y}`;
}

/** The pipeline as a node-flow canvas: the active part is lit, data pulses along its edges, a tile opens its step. */
export function PipelineCanvas({ active, onPick }: { active: NodeId[]; onPick: (id: NodeId) => void }) {
  const calm = useReducedMotion();
  const [hover, setHover] = useState<NodeId | null>(null);
  const lit = new Set(active);
  const shown = hover ? at[hover] : at[active[active.length - 1]] ?? null;
  return (
    <div className="k-pipe">
      <div className="k-pipe-canvas" style={{ aspectRatio: `${W} / ${H}` }}>
        <svg viewBox={`0 0 ${W} ${H}`} className="k-pipe-edges" aria-hidden>
          {EDGES.map(([a, b]) => {
            const on = lit.has(a) && lit.has(b);
            const d = edgePath(a, b);
            return (
              <g key={`${a}-${b}`}>
                <path d={d} className="k-pipe-edge" data-on={on} />
                {on && !calm && (
                  <circle r={4} className="k-pipe-pulse">
                    <animateMotion dur="1.6s" repeatCount="indefinite" path={d} />
                  </circle>
                )}
              </g>
            );
          })}
        </svg>
        {NODES.map((n, i) => {
          const on = lit.has(n.id);
          return (
            <motion.button
              key={n.id}
              className={`k-pipe-node t-${n.tint}`}
              data-on={on}
              style={{ left: `${((n.x - TW / 2) / W) * 100}%`, top: `${((n.y - TH / 2) / H) * 100}%`, width: `${(TW / W) * 100}%`, height: `${(TH / H) * 100}%` }}
              initial={calm ? false : { opacity: 0, y: 12, scale: 0.94 }}
              animate={{ opacity: 1, y: 0, scale: on ? 1.04 : 1 }}
              transition={{ type: "spring", stiffness: 300, damping: 26, delay: calm ? 0 : i * 0.04 }}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(n.id)}
              onBlur={() => setHover(null)}
              onClick={() => onPick(n.id)}
              aria-pressed={on}
            >
              <span className="k-pipe-ico">{n.icon}</span>
              <span className="k-pipe-txt">
                <b>{n.name}</b>
                <span>{n.sub}</span>
              </span>
              <span className="k-pipe-handle in" aria-hidden />
              <span className="k-pipe-handle out" aria-hidden />
            </motion.button>
          );
        })}
      </div>
      {shown && (
        <motion.p key={shown.id} className="k-pipe-detail" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <ComponentInstanceIcon /> <b>{shown.name}.</b> {shown.detail}
        </motion.p>
      )}
    </div>
  );
}

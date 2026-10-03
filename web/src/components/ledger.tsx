"use client";

import { motion, useInView, useReducedMotion } from "motion/react";
import { useRef } from "react";

const INK = { grass: "var(--grass-10)", amber: "var(--amber-10)", red: "var(--red-10)", accent: "var(--accent-10)", plum: "var(--plum-10)" };

/** A rubber stamp that slams onto the page. `play` re-runs the animation when it changes. */
export function Stamp({
  text,
  sub,
  ink = "accent",
  rotate = -8,
  size = 1,
  play = true,
}: {
  text: string;
  sub?: string;
  ink?: keyof typeof INK;
  rotate?: number;
  size?: number;
  play?: boolean;
}) {
  const still = useReducedMotion();
  return (
    <motion.div
      className="stamp"
      style={{ color: INK[ink], fontSize: 28 * size, rotate }}
      initial={still ? false : { opacity: 0, scale: 2.4, rotate: rotate - 14 }}
      animate={play ? { opacity: 1, scale: 1, rotate } : { opacity: 0 }}
      transition={{ type: "spring", stiffness: 520, damping: 22, mass: 0.8 }}
      role="img"
      aria-label={sub ? `${text}: ${sub}` : text}
    >
      <span className="stamp-text">{text}</span>
      {sub && <span className="stamp-sub">{sub}</span>}
    </motion.div>
  );
}

/** Words rise and un-blur one after another when they scroll into view. */
export function SplitText({ text, className, delay = 0, stagger = 0.06 }: { text: string; className?: string; delay?: number; stagger?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const seen = useInView(ref, { once: true, margin: "-60px" });
  return (
    <span ref={ref} className={className} aria-label={text}>
      {text.split(" ").map((w, i) => (
        <motion.span
          key={i}
          aria-hidden
          style={{ display: "inline-block", marginRight: "0.24em", willChange: "transform" }}
          initial={{ opacity: 0, y: "0.6em", filter: "blur(8px)" }}
          animate={seen ? { opacity: 1, y: 0, filter: "blur(0px)" } : undefined}
          transition={{ type: "spring", stiffness: 240, damping: 26, delay: delay + i * stagger }}
        >
          {w}
        </motion.span>
      ))}
    </span>
  );
}

/** An endless ticker. Pauses on hover so a line can be read. */
export function Marquee({ items, speed = 40 }: { items: React.ReactNode[]; speed?: number }) {
  return (
    <div className="marquee" style={{ ["--speed" as string]: `${speed}s` }}>
      <div className="marquee-track">
        {[...items, ...items].map((it, i) => (
          <span key={i} className="marquee-item" aria-hidden={i >= items.length}>
            {it}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Ruled ledger paper with a margin line, for cards that should feel like a written record. */
export function Paper({ children, className = "", style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <div className={`paper ${className}`} style={style}>
      {children}
    </div>
  );
}

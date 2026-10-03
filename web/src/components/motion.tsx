"use client";

import { animate, motion, useInView, useMotionValue, useTransform } from "motion/react";
import { useEffect, useRef } from "react";

export const spring = { type: "spring", stiffness: 260, damping: 28 } as const;

/** Container + item variants: children rise in one after another. */
export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } },
};
export const rise = {
  hidden: { opacity: 0, y: 14, filter: "blur(4px)" },
  show: { opacity: 1, y: 0, filter: "blur(0px)", transition: spring },
};

export function Stagger({ children, className, style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className={className} style={style}>
      {children}
    </motion.div>
  );
}

export function Rise({ children, className, style }: { children: React.ReactNode; className?: string; style?: React.CSSProperties }) {
  return (
    <motion.div variants={rise} className={className} style={style}>
      {children}
    </motion.div>
  );
}

/** Counts up to `value` when it scrolls into view, and re-animates when the value changes. */
export function CountUp({ value, format }: { value: number; format: (n: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const mv = useMotionValue(0);
  const text = useTransform(mv, (n) => format(n));
  useEffect(() => {
    if (!inView) return;
    const c = animate(mv, value, { duration: 0.9, ease: [0.16, 1, 0.3, 1] });
    return () => c.stop();
  }, [inView, value, mv]);
  return (
    <motion.span ref={ref} className="tabular">
      {text}
    </motion.span>
  );
}

/** A horizontal meter whose fill grows in. `tick` marks a reference value (e.g. doing nothing). */
export function Meter({ value, max = 1, muted, tick, delay = 0 }: { value: number; max?: number; muted?: boolean; tick?: number; delay?: number }) {
  const pctOf = (v: number) => `${Math.max(0, Math.min(1, v / max)) * 100}%`;
  return (
    <div className="meter" role="presentation">
      <motion.div
        className={`fill${muted ? " muted" : ""}`}
        initial={{ width: 0 }}
        animate={{ width: pctOf(value) }}
        transition={{ ...spring, delay }}
      />
      {tick !== undefined && (
        <motion.div className="tick" initial={{ opacity: 0 }} animate={{ opacity: 0.55, left: pctOf(tick) }} transition={{ delay: delay + 0.3 }} />
      )}
    </div>
  );
}

"use client";

import { motion, useReducedMotion } from "motion/react";

// A pencil sketch of the idea, drawn stroke by stroke: a calendar with payday circled and ticked,
// and a promise note that gets its tick. Graphite strokes, one maple accent; slight wobble so it reads hand-drawn.
const INK = "var(--k-sketch)";
const RED = "var(--k-red)";

type Stroke = { d: string; at: number; dur?: number; red?: boolean; w?: number };
const NOTE = "M300 330 C 360 322, 440 318, 492 322 C 496 370, 498 420, 494 460 C 440 466, 360 468, 306 466 C 302 420, 300 370, 300 330 Z";
const NOTE_AT = 5.8;

const STROKES: Stroke[] = [
  // calendar page, drawn twice slightly offset like a quick pencil outline
  { d: "M70 92 C 140 88, 330 90, 392 94 C 396 170, 394 300, 390 372 C 300 376, 150 374, 72 370 C 68 280, 68 170, 70 92 Z", at: 0, dur: 1.4 },
  { d: "M74 96 C 160 93, 320 95, 388 98", at: 0.9, dur: 0.6, w: 1 },
  // binding rings
  { d: "M130 78 C 128 90, 130 102, 136 108", at: 1.3, dur: 0.3 },
  { d: "M230 76 C 228 90, 230 102, 236 108", at: 1.4, dur: 0.3 },
  { d: "M330 78 C 328 90, 330 102, 336 108", at: 1.5, dur: 0.3 },
  // header band and month
  { d: "M72 132 C 180 130, 300 131, 392 133", at: 1.6, dur: 0.6 },
  // "OCT"
  { d: "M206 104 C 197 104, 197 121, 206 121 C 215 121, 215 104, 206 104", at: 1.9, dur: 0.4, w: 1.5 },
  { d: "M233 107 C 229 102, 219 103, 219 112 C 219 121, 229 123, 233 117", at: 2.1, dur: 0.35, w: 1.5 },
  { d: "M240 104 L 254 104 M 247 104 L 247 121", at: 2.3, dur: 0.35, w: 1.5 },
  // grid: 4 rows x 6 columns
  ...[176, 220, 264, 308].map((y, i) => ({ d: `M74 ${y} C 180 ${y - 1}, 290 ${y + 1}, 390 ${y}`, at: 2.4 + i * 0.12, dur: 0.5, w: 1 })),
  ...[124, 177, 230, 283, 336].map((x, i) => ({ d: `M${x} 134 C ${x + 1} 220, ${x - 1} 300, ${x} 370`, at: 2.9 + i * 0.1, dur: 0.5, w: 1 })),
  // payday: the 2nd circled in maple, a loose double loop
  { d: "M238 214 C 214 212, 200 236, 214 252 C 230 268, 268 262, 274 240 C 280 218, 256 204, 232 210 C 220 214, 214 222, 214 226", at: 3.7, dur: 0.9, red: true, w: 2.2 },
  // the 2nd: payday
  { d: "M233 229 C 236 221, 249 220, 249 229 C 249 237, 236 243, 232 250 L 251 250", at: 3.5, dur: 0.5, w: 1.6 },
  // payday itself, ticked: the promise falls due that day
  { d: "M268 214 L 278 226 L 298 200", at: 4.8, dur: 0.5, red: true, w: 2.4 },
  // "payday" label with a little leader line
  { d: "M220 268 C 210 290, 196 300, 176 304", at: 5.4, dur: 0.5, w: 1 },
  // promise note, tilted, overlapping the calendar corner
  { d: NOTE, at: NOTE_AT, dur: 1.2 },
  ...[356, 384, 412, 440].map((y, i) => ({ d: `M318 ${y} C 380 ${y - 2}, 440 ${y - 1}, 478 ${y - 3}`, at: 6.6 + i * 0.12, dur: 0.45, w: 0.9 })),
  // a signature scribble
  { d: "M322 438 C 330 420, 338 446, 346 430 C 352 418, 360 444, 370 428 C 376 420, 386 436, 398 430", at: 7.2, dur: 0.8, w: 1.5 },
  // the stamp: "KEPT" boxed, in maple
  { d: "M404 372 C 440 364, 470 362, 486 366 C 488 384, 488 398, 486 410 C 456 414, 428 416, 408 418 C 404 404, 402 388, 404 372 Z", at: 8.0, dur: 0.6, red: true, w: 2 },
  { d: "M418 380 L 418 404 M 418 392 L 430 380 M 420 392 L 432 404 M 440 380 L 440 404 L 452 404 M 440 380 L 452 380 M 440 392 L 450 392 M 460 404 L 460 380 C 472 380, 472 392, 460 392 M 476 380 L 486 380 M 481 380 L 481 404", at: 8.4, dur: 1.0, red: true, w: 1.6 },
  // the pencil itself, resting
  { d: "M120 452 L 250 400 L 262 412 L 132 464 Z M 250 400 C 262 396, 272 400, 276 408 L 262 412 M 120 452 L 104 470 L 132 464", at: 9.0, dur: 1.0, w: 1.4 },
  { d: "M140 446 L 154 459", at: 9.6, dur: 0.3, w: 1 },
];

export function PencilSketch() {
  const still = useReducedMotion() ?? false;
  return (
    <svg viewBox="40 60 480 440" role="img" aria-label="A pencil sketch: a calendar with payday circled and ticked, and a promise note stamped Kept" style={{ width: "100%", height: "100%", overflow: "visible" }}>
      <defs>
        {/* graphite grain: a little turbulence on the strokes */}
        <filter id="graphite" x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence type="fractalNoise" baseFrequency="1.4" numOctaves="2" seed="3" result="noise" />
          <feDisplacementMap in="SourceGraphic" in2="noise" scale="1.6" />
        </filter>
      </defs>
      <Strokes strokes={STROKES.filter((x) => x.at < NOTE_AT)} still={still} />
      {/* the note's paper covers the calendar under it, then its own strokes draw on top */}
      <motion.path
        d={NOTE}
        fill="var(--k-paper)"
        initial={still ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: NOTE_AT * 0.55, duration: 0.3 }}
      />
      <Strokes strokes={STROKES.filter((x) => x.at >= NOTE_AT)} still={still} />
      <motion.text
        x="150"
        y="318"
        fill={INK}
        initial={still ? false : { opacity: 0 }}
        animate={{ opacity: 0.8 }}
        transition={{ delay: 5.6 * 0.55, duration: 0.6 }}
        style={{ font: "300 24px var(--font-hand), 'Segoe Script', cursive" }}
      >
        payday
      </motion.text>
      <motion.text
        x="322"
        y="352"
        fill={INK}
        initial={still ? false : { opacity: 0 }}
        animate={{ opacity: 0.8 }}
        transition={{ delay: 6.4 * 0.55, duration: 0.6 }}
        style={{ font: "300 17px var(--font-hand), 'Segoe Script', cursive" }}
      >
        $140 on Sat, Oct 3
      </motion.text>
    </svg>
  );
}

function Strokes({ strokes, still }: { strokes: Stroke[]; still: boolean }) {
  return (
    <g filter="url(#graphite)" fill="none" strokeLinecap="round" strokeLinejoin="round">
      {strokes.map((s) => (
        <motion.path
          key={s.d}
          d={s.d}
          stroke={s.red ? RED : INK}
          strokeWidth={s.w ?? 1.8}
          initial={still ? false : { pathLength: 0, opacity: 0 }}
          animate={{ pathLength: 1, opacity: s.red ? 0.95 : 0.85 }}
          transition={{
            pathLength: { delay: s.at * 0.55, duration: (s.dur ?? 0.6) * 0.8, ease: [0.45, 0, 0.25, 1] },
            opacity: { delay: s.at * 0.55, duration: 0.05 },
          }}
        />
      ))}
    </g>
  );
}

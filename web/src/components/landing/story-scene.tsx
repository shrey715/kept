"use client";

// The landing's story, driven by scroll progress (0..1):
//   0.00-0.30  records from five systems drift as noise (the cursor parts them)
//   0.30-0.55  they converge: one golden customer per cluster (hover a gold point to read it)
//   0.55-0.75  the camera flies into one customer, Jane; everything else dims
//   0.75-1.00  hold on Jane while the page lays her card, signatures and stamp over the scene
// Client-only (loaded with next/dynamic). Reduced motion: no drift, no cursor push.
import { AdaptiveDpr, Html, PointMaterial, Points, Sparkles } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing";
import type { MotionValue } from "motion/react";
import { useMemo, useRef, useState } from "react";
import { AdditiveBlending, Color, NormalBlending, type Group, type Points as ThreePoints, Vector3 } from "three";

// opaque canvas in the page colour: bloom needs an opaque target
export const BACKGROUND = { dark: "#0d0a09", light: "#faf7f2" };
export const SYSTEMS = [
  { name: "CRM", color: "#e5484d" },
  { name: "Card", color: "#6e6ade" },
  { name: "Loan", color: "#00a2c7" },
  { name: "Deposit", color: "#46a758" },
  { name: "Collections", color: "#ffc53d" },
];
const RECORDS = 5000;
const CUSTOMERS = 140;
const JANE = 0; // the cluster the camera flies into
const COLORS = SYSTEMS.map((s) => new Color(s.color));
// on paper, additive glow washes out: deeper inks and normal blending instead
const INK = ["#b4232c", "#4740b3", "#0b7896", "#2a7e3b", "#a35c00"].map((c) => new Color(c));
const JANE_KEYS = ["CRM · JDO-4037", "Card · C-88201", "Loan · L-5530921", "Deposit · D-51011", "Collections · CS-2026-118204"];

function seeded(seed: number) {
  let s = seed;
  return () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
}

const clamp01 = (t: number) => Math.min(1, Math.max(0, t));
const ease = (t: number) => 1 - Math.pow(1 - clamp01(t), 3);
const span = (p: number, a: number, b: number) => ease((p - a) / (b - a));

function useField(light: boolean) {
  return useMemo(() => {
    const rnd = seeded(7);
    const centers = new Float32Array(CUSTOMERS * 3);
    for (let i = 0; i < CUSTOMERS; i++) {
      const y = 1 - (i / (CUSTOMERS - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const t = Math.PI * (3 - Math.sqrt(5)) * i;
      const R = 2.6 + rnd() * 0.5;
      centers.set([Math.cos(t) * r * R, y * R * 0.82, Math.sin(t) * r * R], i * 3);
    }
    centers.set([0.4, 0.2, 2.9], JANE * 3); // Jane sits at the front of the shell
    const start = new Float32Array(RECORDS * 3);
    const target = new Float32Array(RECORDS * 3);
    const colors = new Float32Array(RECORDS * 3);
    const phase = new Float32Array(RECORDS);
    const cluster = new Uint16Array(RECORDS);
    for (let i = 0; i < RECORDS; i++) {
      const c = i < 5 ? JANE : Math.floor(rnd() * CUSTOMERS); // Jane: exactly one record per system
      cluster[i] = c;
      start.set([(rnd() - 0.5) * 22, (rnd() - 0.5) * 13, (rnd() - 0.5) * 12 - 2], i * 3);
      const j = c === JANE ? 0.9 : 0.09;
      target.set(
        [centers[c * 3] + (rnd() - 0.5) * j, centers[c * 3 + 1] + (rnd() - 0.5) * j, centers[c * 3 + 2] + (rnd() - 0.5) * j],
        i * 3,
      );
      const col = (light ? INK : COLORS)[i % 5];
      colors.set([col.r, col.g, col.b], i * 3);
      phase[i] = rnd() * Math.PI * 2;
    }
    return { centers, start, target, colors, phase, cluster };
  }, [light]);
}

type Hover = { index: number; x: number; y: number; z: number } | null;

function Field({ progress, still, light }: { progress: MotionValue<number>; still: boolean; light: boolean }) {
  const f = useField(light);
  const jane = useMemo(() => f.target.slice(0, 15), [f]); // Jane's five records, one per system
  const janeColors = useMemo(() => f.colors.slice(0, 15), [f]);
  const janeRef = useRef<ThreePoints>(null);
  const [zoomed, setZoomed] = useState(false);
  const group = useRef<Group>(null);
  const records = useRef<ThreePoints>(null);
  const golden = useRef<ThreePoints>(null);
  const positions = useMemo(() => f.start.slice(), [f]);
  const colors = useMemo(() => f.colors.slice(), [f]);
  const [hover, setHover] = useState<Hover>(null);
  const { camera, viewport } = useThree();
  const cam = useMemo(() => ({ far: new Vector3(0, 0, 8.5), near: new Vector3(0.4, 0.2, 5.0), look: new Vector3() }), []);
  const pointerWorld = useMemo(() => new Vector3(), []);
  const bg = useMemo(() => new Color(light ? BACKGROUND.light : BACKGROUND.dark), [light]);

  useFrame(({ clock, pointer }) => {
    const t = still ? 0 : clock.elapsedTime;
    const p = progress.get();
    const merge = span(p, 0.3, 0.55);
    const zoom = span(p, 0.55, 0.75);

    // camera: fly into Jane, look at her cluster
    camera.position.lerpVectors(cam.far, cam.near, zoom);
    cam.look.set(f.centers[JANE * 3] * zoom, f.centers[JANE * 3 + 1] * zoom, f.centers[JANE * 3 + 2] * zoom * 0.6);
    camera.lookAt(cam.look);

    // the cursor, projected onto the z=0 plane, parts the scattered records
    pointerWorld.set((pointer.x * viewport.width) / 2, (pointer.y * viewport.height) / 2, 0);
    const push = still ? 0 : (1 - merge) * 1.1;

    if (records.current) {
      const pos = records.current.geometry.attributes.position.array as Float32Array;
      const col = records.current.geometry.attributes.color.array as Float32Array;
      const wobble = still ? 0 : (1 - merge) * 0.5 + 0.012;
      for (let i = 0; i < RECORDS; i++) {
        const k = i * 3;
        const ph = f.phase[i];
        let x = f.start[k] + (f.target[k] - f.start[k]) * merge + Math.sin(t * 0.9 + ph) * wobble;
        let y = f.start[k + 1] + (f.target[k + 1] - f.start[k + 1]) * merge + Math.cos(t * 0.7 + ph * 1.3) * wobble;
        const z = f.start[k + 2] + (f.target[k + 2] - f.start[k + 2]) * merge + Math.sin(t * 0.5 + ph * 0.7) * wobble;
        if (push > 0) {
          const dx = x - pointerWorld.x, dy = y - pointerWorld.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < 2.2) {
            const s = (push * (2.2 - d2)) / 2.2 / Math.sqrt(d2 + 0.01);
            x += dx * s * 0.5;
            y += dy * s * 0.5;
          }
        }
        pos[k] = x;
        pos[k + 1] = y;
        pos[k + 2] = z;
        // when zoomed, everyone but Jane fades into the page (black or paper)
        const fade = f.cluster[i] === JANE ? 0 : zoom * 0.92;
        col[k] = f.colors[k] + (bg.r - f.colors[k]) * fade;
        col[k + 1] = f.colors[k + 1] + (bg.g - f.colors[k + 1]) * fade;
        col[k + 2] = f.colors[k + 2] + (bg.b - f.colors[k + 2]) * fade;
      }
      records.current.geometry.attributes.position.needsUpdate = true;
      records.current.geometry.attributes.color.needsUpdate = true;
    }
    if (janeRef.current) {
      const m = janeRef.current.material as unknown as { opacity: number };
      m.opacity = zoom;
    }
    if ((zoom > 0.6) !== zoomed) setZoomed(zoom > 0.6);
    if (golden.current) {
      const m = golden.current.material as unknown as { opacity: number };
      m.opacity = clamp01((merge - 0.6) / 0.4) * (1 - zoom * 0.7) * (still ? 1 : 0.85 + Math.sin(t * 2) * 0.15);
    }
    if (group.current) {
      const turn = (1 - zoom) * (still ? 0 : 1);
      group.current.rotation.y += 0.0016 * turn;
      group.current.rotation.y *= 1 - zoom * 0.08; // settle to face the camera as we fly in
      group.current.rotation.x += ((still ? 0 : pointer.y * 0.15) * turn - group.current.rotation.x) * 0.05;
    }
  });

  const showHover = hover && progress.get() > 0.42 && progress.get() < 0.6;
  return (
    <group ref={group}>
      <Points ref={records} positions={positions} colors={colors} stride={3}>
        <PointMaterial transparent vertexColors size={light ? 0.04 : 0.034} sizeAttenuation depthWrite={false} blending={light ? NormalBlending : AdditiveBlending} opacity={light ? 0.75 : 0.5} />
      </Points>
      <Points
        ref={golden}
        positions={f.centers}
        stride={3}
        onPointerMove={(e) => {
          if (e.index === undefined) return;
          const k = e.index * 3;
          setHover({ index: e.index, x: f.centers[k], y: f.centers[k + 1], z: f.centers[k + 2] });
        }}
        onPointerOut={() => setHover(null)}
      >
        <PointMaterial transparent color={light ? "#b45309" : "#ffcf87"} size={0.12} sizeAttenuation depthWrite={false} blending={light ? NormalBlending : AdditiveBlending} opacity={0} />
      </Points>
      {/* Jane, up close: her five records around one golden ID */}
      <Points ref={janeRef} positions={jane} colors={janeColors} stride={3}>
        <PointMaterial transparent vertexColors size={0.16} sizeAttenuation depthWrite={false} blending={light ? NormalBlending : AdditiveBlending} opacity={0} />
      </Points>
      {zoomed && (
        <>
          <Html position={[f.centers[0], f.centers[1], f.centers[2]]} center style={{ pointerEvents: "none" }}>
            <div className="scene-node">G-910001</div>
          </Html>
          {JANE_KEYS.map((k, i) => (
            <Html key={k} position={[jane[i * 3], jane[i * 3 + 1], jane[i * 3 + 2]]} style={{ pointerEvents: "none" }}>
              <div className="scene-key" style={{ borderColor: SYSTEMS[i].color }}>{k}</div>
            </Html>
          ))}
        </>
      )}
      {showHover && hover && (
        <Html position={[hover.x, hover.y, hover.z]} center style={{ pointerEvents: "none" }}>
          <div className="scene-tip">
            <b>G-{910001 + hover.index}</b>
            <span>{hover.index === JANE ? "Jane D." : "1 customer"} · 5 records</span>
            <i>
              {SYSTEMS.map((s) => (
                <em key={s.name} style={{ background: s.color }} />
              ))}
            </i>
          </div>
        </Html>
      )}
    </group>
  );
}

export default function StoryScene({ progress, still = false, light = false }: { progress: MotionValue<number>; still?: boolean; light?: boolean }) {
  return (
    <Canvas
      camera={{ position: [0, 0, 8.5], fov: 50 }}
      dpr={[1, 1.75]}
      gl={{ antialias: false, alpha: false, powerPreference: "high-performance" }}
      raycaster={{ params: { Points: { threshold: 0.12 } } as never }}
      style={{ position: "absolute", inset: 0 }}
    >
      <color attach="background" args={[light ? BACKGROUND.light : BACKGROUND.dark]} />
      <AdaptiveDpr pixelated />
      <Field progress={progress} still={still} light={light} />
      {!still && <Sparkles count={110} scale={[16, 9, 6]} size={2} speed={0.25} color={light ? "#c8102e" : "#ffb3a1"} opacity={light ? 0.25 : 0.45} />}
      {!light && (
        <EffectComposer>
          <Bloom intensity={1.35} luminanceThreshold={0.05} luminanceSmoothing={0.4} mipmapBlur />
          <Vignette eskil={false} offset={0.2} darkness={0.8} />
        </EffectComposer>
      )}
    </Canvas>
  );
}

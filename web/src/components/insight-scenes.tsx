"use client";

// The two 3D views on the Insights page, client-only (next/dynamic, no SSR):
//   CollectionsTowers (#102): tonight's overdue balance by postal district, hexbinned towers on the provinces;
//     height = overdue, colour = the bank's 30-day roll rate, or Kept's tier mix stacked in the tower.
//     Opens with a slow fly-in from the Atlantic westward (none with reduced motion).
//   UpliftSurface (#109): the live uplift model's call-minus-wait surface over days past due x answer rate,
//     with tonight's cases as groups of 50 or more, coloured by their card's action.
import { Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useReducedMotion } from "motion/react";
import { useTheme } from "next-themes";
import { useEffect, useMemo, useRef, useState } from "react";
import { BufferAttribute, BufferGeometry, CatmullRomCurve3, Color, CylinderGeometry, DoubleSide, Vector3 } from "three";
import { ACTION_LABEL, money, type Action, type CollectionsMap, type UpliftLandscape } from "@/lib/api";
import { bounds, loadProvinces, project, type Province } from "@/lib/geo";
import { ACTION_COLOR } from "./insight-maps";

const pct = (v: number, d = 0) => `${(v * 100).toFixed(d)}%`;
const n = (v: number) => Math.round(v).toLocaleString("en-CA");

function useInk() {
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  return { dark, line: dark ? "#d9d1c6" : "#3b3530", grey: dark ? "#57524c" : "#b9b2a9" };
}

// ------------------------------------------------------------------ collections towers (#102)
const S = 12; // plane units per projected unit
const R = 0.16; // hex radius
const MAX_H = 3.2;
const TIERS = [
  { key: "green", color: "#3e9b5c", label: "Green" },
  { key: "amber", color: "#e2a336", label: "Amber" },
  { key: "red", color: "#c8102e", label: "Red" },
  { key: "none", color: "#a8a29e", label: "No action" },
] as const;
const ROLL = [new Color("#3e9b5c"), new Color("#e2a336"), new Color("#c8102e")];

type Bin = {
  id: string;
  x: number;
  z: number;
  fsas: { fsa: string; city: string | null; cases: number }[];
  cases: number;
  overdue: number;
  roll: number | null;
  rollBase: number;
  hardship: number;
  green: number;
  amber: number;
  red: number;
  none: number;
};

function hexbin(data: CollectionsMap, to: (lon: number, lat: number) => [number, number]): Bin[] {
  const bins = new Map<string, Bin & { rollSum: number; hardSum: number }>();
  for (const t of data.towers) {
    const [x, z] = to(t.lon, t.lat);
    // pointy-top axial coordinates, rounded in cube space
    const qf = ((Math.sqrt(3) / 3) * x - z / 3) / R;
    const rf = ((2 / 3) * z) / R;
    let [q, r] = [Math.round(qf), Math.round(rf)];
    const s = Math.round(-qf - rf);
    const [dq, dr, ds] = [Math.abs(q - qf), Math.abs(r - rf), Math.abs(s + qf + rf)];
    if (dq > dr && dq > ds) q = -r - s;
    else if (dr > ds) r = -q - s;
    const id = `${q},${r}`;
    const b =
      bins.get(id) ??
      ({ id, x: R * Math.sqrt(3) * (q + r / 2), z: R * 1.5 * r, fsas: [], cases: 0, overdue: 0, roll: null, rollBase: 0, hardship: 0, green: 0, amber: 0, red: 0, none: 0, rollSum: 0, hardSum: 0 } as Bin & {
        rollSum: number;
        hardSum: number;
      });
    b.fsas.push({ fsa: t.fsa, city: t.city, cases: t.cases });
    b.cases += t.cases;
    b.overdue += t.overdue;
    b.hardSum += t.hardship * t.cases;
    if (t.roll_rate != null) {
      b.rollSum += t.roll_rate * t.roll_base;
      b.rollBase += t.roll_base;
    }
    for (const k of ["green", "amber", "red", "none"] as const) b[k] += t[k];
    bins.set(id, b);
  }
  return [...bins.values()].map((b) => ({ ...b, roll: b.rollBase ? b.rollSum / b.rollBase : null, hardship: b.hardSum / b.cases, fsas: b.fsas.sort((a, c) => c.cases - a.cases) }));
}

function rollColor(v: number | null, lo: number, hi: number, grey: string) {
  if (v == null) return new Color(grey);
  const t = Math.min(1, Math.max(0, (v - lo) / (hi - lo || 1))) * 2;
  return t <= 1 ? ROLL[0].clone().lerp(ROLL[1], t) : ROLL[1].clone().lerp(ROLL[2], t - 1);
}

export function CollectionsTowers({ data, mode }: { data: CollectionsMap; mode: "roll" | "tier" }) {
  const calm = useReducedMotion() ?? false;
  const ink = useInk();
  const [shapes, setShapes] = useState<Province[] | null>(null);
  const [hover, setHover] = useState<Bin | null>(null);
  const [take, setTake] = useState(0); // bump to replay the fly-in
  useEffect(() => {
    let live = true;
    loadProvinces().then((s) => live && setShapes(s), () => undefined);
    return () => {
      live = false;
    };
  }, []);

  const scene = useMemo(() => {
    if (!shapes) return null;
    const [x0, y0, x1, y1] = bounds(shapes);
    const [cx, cy] = [(x0 + x1) / 2, (y0 + y1) / 2];
    const plane = (x: number, y: number): [number, number] => [(x - cx) * S, -(y - cy) * S];
    const to = (lon: number, lat: number) => plane(...project(lon, lat));
    const bins = hexbin(data, to);
    const rolls = bins.map((b) => b.roll).filter((v): v is number => v != null);
    const outlines = shapes.flatMap((p) => p.polygons.map((r) => r.map(([x, y]) => new Vector3(plane(x, y)[0], 0, plane(x, y)[1]))));
    const focus = bins.reduce((a, b) => a.add(new Vector3(b.x * b.cases, 0, b.z * b.cases)), new Vector3()).divideScalar(Math.max(1, data.towers.reduce((s, t) => s + t.cases, 0)));
    return { bins, outlines, focus, lo: Math.min(...rolls), hi: Math.max(...rolls), top: Math.max(...bins.map((b) => b.overdue), 1) };
  }, [shapes, data]);

  const geo = useMemo(() => {
    const g = new CylinderGeometry(R * 0.9, R * 0.9, 1, 6);
    g.translate(0, 0.5, 0);
    g.rotateY(Math.PI / 6);
    return g;
  }, []);

  return (
    <div className="k-scene">
      <Canvas camera={{ position: [0, 9, 10], fov: 38, near: 0.1, far: 200 }} dpr={[1, 2]} gl={{ antialias: true, alpha: true }} frameloop={calm ? "demand" : "always"}>
        <ambientLight intensity={0.75} />
        <directionalLight position={[6, 12, 8]} intensity={1.1} />
        {scene && (
          <>
            {scene.outlines.map((pts, i) => (
              <Line key={i} points={pts} color={ink.line} lineWidth={0.8} transparent opacity={0.35} />
            ))}
            {scene.bins.map((b) => {
              const h = Math.max(0.03, (b.overdue / scene.top) * MAX_H);
              const lit = hover?.id === b.id;
              const over = { onPointerOver: (e: { stopPropagation: () => void }) => (e.stopPropagation(), setHover(b)), onPointerOut: () => setHover((x) => (x?.id === b.id ? null : x)) };
              if (mode === "roll")
                return (
                  <mesh key={b.id} geometry={geo} position={[b.x, 0, b.z]} scale={[1, h, 1]} {...over}>
                    <meshStandardMaterial color={rollColor(b.roll, scene.lo, scene.hi, ink.grey)} emissive={lit ? "#ffffff" : "#000000"} emissiveIntensity={lit ? 0.25 : 0} roughness={0.55} />
                  </mesh>
                );
              let y = 0;
              return (
                <group key={b.id} {...over}>
                  {TIERS.map((t) => {
                    const part = (b[t.key] / b.cases) * h;
                    const at = y;
                    y += part;
                    return part > 0 ? (
                      <mesh key={t.key} geometry={geo} position={[b.x, at, b.z]} scale={[1, part, 1]}>
                        <meshStandardMaterial color={t.key === "none" ? ink.grey : t.color} emissive={lit ? "#ffffff" : "#000000"} emissiveIntensity={lit ? 0.25 : 0} roughness={0.55} />
                      </mesh>
                    ) : null;
                  })}
                </group>
              );
            })}
            <FlyIn key={take} focus={scene.focus} still={calm} />
          </>
        )}
      </Canvas>

      <div className="k-scene-tip" data-show={!!hover}>
        {hover && (
          <>
            <b>{hover.fsas.slice(0, 4).map((f) => f.fsa).join(", ")}</b>
            {hover.fsas.length > 4 && ` and ${hover.fsas.length - 4} more`}
            {hover.fsas[0].city && <span className="k-scene-sub"> · {hover.fsas[0].city}</span>}
            <dl>
              <dt>Cases</dt>
              <dd>{n(hover.cases)}</dd>
              <dt>Overdue</dt>
              <dd>{money(hover.overdue)}</dd>
              <dt>30-day roll rate</dt>
              <dd>{hover.roll == null ? "too few cases" : pct(hover.roll, 1)}</dd>
              <dt>Hardship cards</dt>
              <dd>{pct(hover.hardship, 1)}</dd>
              <dt>Tier mix</dt>
              <dd>
                {pct(hover.green / hover.cases)} green · {pct(hover.amber / hover.cases)} amber · {pct(hover.red / hover.cases)} red
              </dd>
            </dl>
          </>
        )}
      </div>
      <div className="k-scene-legend">
        {mode === "roll" && scene ? (
          <>
            <span className="tabular">{pct(scene.lo)}</span>
            <span className="k-scene-ramp" />
            <span className="tabular">{pct(scene.hi)}</span>
            <span>30-day roll rate</span>
          </>
        ) : (
          TIERS.map((t) => (
            <span key={t.key} className="k-scene-key">
              <i style={{ background: t.key === "none" ? ink.grey : t.color }} />
              {t.label}
            </span>
          ))
        )}
        {!calm && (
          <button className="k-text-btn" onClick={() => setTake((x) => x + 1)}>
            Replay the fly-in
          </button>
        )}
      </div>
    </div>
  );
}

/** From low over the Atlantic, westward across the country, up to the overview. Still: the overview at once. */
function FlyIn({ focus, still }: { focus: Vector3; still: boolean }) {
  const { camera } = useThree();
  const start = useRef<number | null>(null);
  const [done, setDone] = useState(still);
  const end = useMemo(() => focus.clone().add(new Vector3(0, 8.5, 7.5)), [focus]);
  const path = useMemo(() => new CatmullRomCurve3([new Vector3(9.5, 0.9, 2.4), new Vector3(4, 2.4, 3.6), new Vector3(-3.5, 4.6, 5), end]), [end]);
  const look = useMemo(() => new CatmullRomCurve3([new Vector3(5, 0, -0.2), new Vector3(1, 0, 0), new Vector3(-3, 0, 0.4), focus.clone()]), [focus]);
  useEffect(() => {
    if (!still) return;
    camera.position.copy(end);
    camera.lookAt(focus);
  }, [still, camera, end, focus]);
  useFrame(({ clock }) => {
    if (done) return;
    start.current ??= clock.elapsedTime;
    const p = Math.min(1, (clock.elapsedTime - start.current) / 9);
    const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
    camera.position.copy(path.getPoint(e));
    camera.lookAt(look.getPoint(e));
    if (p >= 1) setDone(true);
  });
  // the controls take over once the camera has landed, aimed where it looks
  return done ? <OrbitControls makeDefault target={focus} enableDamping maxPolarAngle={Math.PI / 2.1} minDistance={2} maxDistance={30} /> : null;
}

// ------------------------------------------------------------------ uplift surface (#109)
const SX = 6; // days past due across
const SZ = 4; // answer rate deep
const SY = 2.2; // the largest uplift's height

export function UpliftSurface({ data }: { data: UpliftLandscape }) {
  const calm = useReducedMotion() ?? false;
  const ink = useInk();
  const [hover, setHover] = useState<UpliftLandscape["groups"][number] | null>(null);
  const maxD = data.dpd[data.dpd.length - 1] || 1;
  const big = Math.max(...data.uplift.flat().map(Math.abs), ...data.groups.map((g) => Math.abs(g.uplift)), 1e-6);
  const at = (dpd: number, ans: number, u: number) => new Vector3((Math.min(dpd, maxD) / maxD - 0.5) * SX, (u / big) * SY, (0.5 - ans) * SZ);

  const geometry = useMemo(() => {
    const [nx, nz] = [data.dpd.length, data.answer_rate.length];
    const pos = new Float32Array(nx * nz * 3);
    const col = new Float32Array(nx * nz * 3);
    const flat = new Color(ink.dark ? "#3b3530" : "#e4ddd2");
    const up = new Color("#2f8f57");
    const down = new Color("#c8102e");
    data.answer_rate.forEach((a, j) =>
      data.dpd.forEach((d, i) => {
        const u = data.uplift[j][i];
        const v = at(d, a, u);
        pos.set([v.x, v.y, v.z], (j * nx + i) * 3);
        const c = flat.clone().lerp(u >= 0 ? up : down, Math.min(1, Math.abs(u) / big) ** 0.7);
        col.set([c.r, c.g, c.b], (j * nx + i) * 3);
      }),
    );
    const idx: number[] = [];
    for (let j = 0; j < nz - 1; j++)
      for (let i = 0; i < nx - 1; i++) {
        const k = j * nx + i;
        idx.push(k, k + nx, k + 1, k + 1, k + nx, k + nx + 1);
      }
    const g = new BufferGeometry();
    g.setAttribute("position", new BufferAttribute(pos, 3));
    g.setAttribute("color", new BufferAttribute(col, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    return g;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, ink.dark, big]);

  const most = Math.max(...data.groups.map((g) => g.cases), 1);
  const actions = [...new Set(data.groups.map((g) => g.action))];

  return (
    <div className="k-scene">
      <Canvas camera={{ position: [5.2, 4.2, 6.2], fov: 38 }} dpr={[1, 2]} gl={{ antialias: true, alpha: true }} frameloop={calm ? "demand" : "always"}>
        <ambientLight intensity={0.8} />
        <directionalLight position={[4, 10, 6]} intensity={0.9} />
        <mesh geometry={geometry}>
          <meshStandardMaterial vertexColors side={DoubleSide} roughness={0.7} transparent opacity={0.92} />
        </mesh>
        <mesh geometry={geometry}>
          <meshBasicMaterial wireframe color={ink.line} transparent opacity={0.12} />
        </mesh>
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <planeGeometry args={[SX, SZ]} />
          <meshBasicMaterial color={ink.line} transparent opacity={0.05} side={DoubleSide} depthWrite={false} />
        </mesh>
        <Line points={[[-SX / 2, 0, SZ / 2], [SX / 2, 0, SZ / 2]]} color={ink.line} lineWidth={1} transparent opacity={0.5} />
        <Line points={[[-SX / 2, 0, SZ / 2], [-SX / 2, 0, -SZ / 2]]} color={ink.line} lineWidth={1} transparent opacity={0.5} />
        <Line points={[[-SX / 2, -SY, -SZ / 2], [-SX / 2, SY, -SZ / 2]]} color={ink.line} lineWidth={1} transparent opacity={0.5} />
        {data.groups.map((g, i) => (
          <mesh
            key={i}
            position={at(g.dpd, g.answer_rate, g.uplift)}
            onPointerOver={(e) => (e.stopPropagation(), setHover(g))}
            onPointerOut={() => setHover((x) => (x === g ? null : x))}
          >
            <sphereGeometry args={[0.045 + 0.09 * Math.sqrt(g.cases / most), 16, 12]} />
            <meshStandardMaterial color={ACTION_COLOR[g.action] ?? ACTION_COLOR.none} emissive={hover === g ? "#ffffff" : "#000000"} emissiveIntensity={hover === g ? 0.35 : 0} />
          </mesh>
        ))}
        <OrbitControls makeDefault enableDamping autoRotate={!calm} autoRotateSpeed={0.35} maxPolarAngle={Math.PI / 1.9} minDistance={3} maxDistance={18} />
      </Canvas>

      <div className="k-scene-tip" data-show={!!hover}>
        {hover && (
          <>
            <b>{hover.action === "none" ? "No action" : (ACTION_LABEL[hover.action as Action] ?? hover.action)}</b>
            <span className="k-scene-sub"> · {n(hover.cases)} cases</span>
            <dl>
              <dt>Days past due</dt>
              <dd>{hover.dpd.toFixed(0)} on average</dd>
              <dt>Answer rate</dt>
              <dd>{pct(hover.answer_rate)}</dd>
              <dt>Call uplift</dt>
              <dd>
                {hover.uplift >= 0 ? "+" : "−"}
                {Math.abs(hover.uplift * 100).toFixed(1)} pts paid in 14 days
              </dd>
            </dl>
          </>
        )}
      </div>
      <div className="k-scene-axes">
        Across: days past due, 0 to {maxD}
        <br />
        Depth: answer rate, 0% in front to 100% at the back
        <br />
        Height: call uplift, up to {(big * 100).toFixed(1)} points either way
      </div>
      <div className="k-scene-legend">
        {actions.map((a) => (
          <span key={a} className="k-scene-key">
            <i style={{ background: ACTION_COLOR[a] ?? ACTION_COLOR.none }} />
            {a === "none" ? "No action" : (ACTION_LABEL[a as Action] ?? a)}
          </span>
        ))}
      </div>
    </div>
  );
}
